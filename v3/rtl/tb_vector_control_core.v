`timescale 1ns/1ps
`default_nettype none

module tb_vector_control_core;
    reg clk = 1'b0;
    reg rst_n = 1'b1;
    reg ena = 1'b0;
    reg [2:0] beam_select = 3'd0;
    reg raw_mode = 1'b0;
    reg [3:0] channel_enable = 4'hF;
    reg cfg_clk = 1'b0;
    reg cfg_data = 1'b0;
    reg cfg_latch = 1'b0;

    wire [3:0] phase_wave;
    wire [15:0] group_lo_p;
    wire [15:0] group_lo_n;
    wire [31:0] active_vector_words;
    wire [3:0] active_channel_enable;
    wire [3:0] channel_bias_enable;
    wire mixers_blank;

    v3_vector_control_core dut (
        .clk(clk),
        .rst_n(rst_n),
        .ena(ena),
        .beam_select(beam_select),
        .raw_mode(raw_mode),
        .channel_enable(channel_enable),
        .cfg_clk(cfg_clk),
        .cfg_data(cfg_data),
        .cfg_latch(cfg_latch),
        .phase_wave(phase_wave),
        .group_lo_p(group_lo_p),
        .group_lo_n(group_lo_n),
        .active_vector_words(active_vector_words),
        .active_channel_enable(active_channel_enable),
        .channel_bias_enable(channel_bias_enable),
        .mixers_blank(mixers_blank)
    );

    always #31.25 clk = ~clk;

    task require;
        input condition;
        input [8*112-1:0] message;
        begin
            if (!condition) begin
                $display("FAIL: %0s", message);
                $fatal(1);
            end
        end
    endtask

    task wait_for_unblank;
        integer cycles;
        begin
            cycles = 0;
            while (mixers_blank && cycles < 24) begin
                @(posedge clk);
                #1;
                cycles = cycles + 1;
            end
            require(!mixers_blank, "mixers did not unblank");
        end
    endtask

    task shift_config;
        input [31:0] value;
        integer bit_index;
        begin
            for (bit_index = 0; bit_index < 32; bit_index = bit_index + 1) begin
                cfg_data = value[bit_index];
                #10 cfg_clk = 1'b1;
                #10 cfg_clk = 1'b0;
            end
            cfg_latch = 1'b1;
            #10 cfg_clk = 1'b1;
            #10 cfg_clk = 1'b0;
            cfg_latch = 1'b0;
        end
    endtask

    integer blank_cycles;
    initial begin
        #1 rst_n = 1'b0;
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        ena = 1'b1;

        wait_for_unblank();
        while (active_channel_enable != 4'hF)
            @(posedge clk);
        #1;
        require(mixers_blank, "initial channel enable bypassed safe commit");
        require(channel_bias_enable == 4'h0, "tail bias stayed active while blanked");
        wait_for_unblank();
        require(active_vector_words == 32'h08080808, "beam-zero reset LUT mismatch");
        require((group_lo_p ^ group_lo_n) == 16'hFFFF, "group LO pairs are not complementary");
        require(channel_bias_enable == 4'hF, "enabled channels lost tail bias");

        beam_select = 3'd1;
        @(posedge mixers_blank);
        blank_cycles = 0;
        while (mixers_blank && blank_cycles < 12) begin
            @(posedge clk);
            #1;
            blank_cycles = blank_cycles + 1;
        end
        require(blank_cycles >= 4, "beam update blanked for less than one LO period");
        require(!mixers_blank, "beam update never left blanking interval");
        require(active_vector_words == 32'hBFF7C008, "beam-one vector words mismatch");

        raw_mode = 1'b1;
        shift_config(32'hDEADBEEF);
        while (active_vector_words != 32'hDEADBEEF)
            @(posedge clk);
        #1;
        require(mixers_blank, "raw coefficient update did not blank analog cells");
        require(channel_bias_enable == 4'h0, "tail bias active during raw update");
        wait_for_unblank();
        require((group_lo_p ^ group_lo_n) == 16'hFFFF, "raw group LO pairs lost complement");

        channel_enable = 4'b0101;
        while (active_channel_enable != 4'b0101)
            @(posedge clk);
        #1;
        require(mixers_blank, "channel mask update did not blank analog cells");
        wait_for_unblank();
        require(channel_bias_enable == 4'b0101, "tail-bias enable does not follow channel mask");
        require((group_lo_p[7:4] | group_lo_n[7:4]) == 4'h0, "disabled channel one LO toggled");
        require((group_lo_p[15:12] | group_lo_n[15:12]) == 4'h0, "disabled channel three LO toggled");
        require((group_lo_p[3:0] ^ group_lo_n[3:0]) == 4'hF, "enabled channel zero lost complement");
        require((group_lo_p[11:8] ^ group_lo_n[11:8]) == 4'hF, "enabled channel two lost complement");

        ena = 1'b0;
        repeat (3) @(posedge clk);
        #1;
        require(mixers_blank, "ena low did not blank analog cells");
        require(group_lo_p == 16'h0 && group_lo_n == 16'h0, "LO active while disabled");
        require(channel_bias_enable == 4'h0, "tail bias active while disabled");

        $display("PASS: V3 LUT, 32-bit atomic raw update, group LO selection, and bias blanking");
        $finish;
    end

    initial begin
        #150000;
        $fatal(1, "V3 vector-control testbench timeout");
    end
endmodule

`default_nettype wire
