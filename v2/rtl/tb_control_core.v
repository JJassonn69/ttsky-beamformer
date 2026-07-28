`timescale 1ns/1ps
`default_nettype none

module tb_control_core;
    reg clk = 1'b0;
    reg rst_n = 1'b1;
    reg ena = 1'b0;
    reg [1:0] beam_select = 2'b00;
    reg manual_mode = 1'b0;
    reg [3:0] channel_enable = 4'hF;
    reg cfg_clk = 1'b0;
    reg cfg_data = 1'b0;
    reg cfg_latch = 1'b0;

    wire [3:0] phase_wave;
    wire [3:0] channel_lo_p;
    wire [3:0] channel_lo_n;
    wire [7:0] active_phase_codes;
    wire [15:0] active_trim_codes;
    wire [3:0] active_channel_enable;
    wire mixers_blank;

    v2_control_core dut (
        .clk(clk),
        .rst_n(rst_n),
        .ena(ena),
        .beam_select(beam_select),
        .manual_mode(manual_mode),
        .channel_enable(channel_enable),
        .cfg_clk(cfg_clk),
        .cfg_data(cfg_data),
        .cfg_latch(cfg_latch),
        .phase_wave(phase_wave),
        .channel_lo_p(channel_lo_p),
        .channel_lo_n(channel_lo_n),
        .active_phase_codes(active_phase_codes),
        .active_trim_codes(active_trim_codes),
        .active_channel_enable(active_channel_enable),
        .mixers_blank(mixers_blank)
    );

    always #31.25 clk = ~clk; // 16 MHz

    task require;
        input condition;
        input [8*96-1:0] message;
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
        input [23:0] value;
        integer bit_index;
        begin
            for (bit_index = 0; bit_index < 24; bit_index = bit_index + 1) begin
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
        if ($test$plusargs("vcd")) begin
            $dumpfile("build/v2/control_core.vcd");
            $dumpvars(0, tb_control_core);
        end

        #1 rst_n = 1'b0;
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        ena = 1'b1;

        wait_for_unblank();
        while (active_channel_enable != 4'hF)
            @(posedge clk);
        #1;
        require(mixers_blank, "initial channel mask did not use a safe commit");
        wait_for_unblank();
        require(active_phase_codes == 8'h00, "reset phase codes are not beam zero");
        require(active_trim_codes == 16'h8888, "reset trim codes are not nominal");
        require(active_channel_enable == 4'hF, "channel mask was not safely committed");
        require((channel_lo_p ^ channel_lo_n) == 4'hF, "enabled LO pairs are not complementary");

        beam_select = 2'd1;
        @(posedge mixers_blank);
        blank_cycles = 0;
        while (mixers_blank && blank_cycles < 12) begin
            @(posedge clk);
            #1;
            blank_cycles = blank_cycles + 1;
        end
        require(blank_cycles >= 4, "beam update blanked for less than one LO period");
        require(!mixers_blank, "beam update never left blanking interval");
        require(active_phase_codes == 8'h6C, "beam-one RX phase codes were not committed");
        require((channel_lo_p ^ channel_lo_n) == 4'hF, "LO pairs lost complement after beam update");

        manual_mode = 1'b1;
        shift_config({16'hF840, 8'h1B});
        while (active_trim_codes != 16'hF840)
            @(posedge clk);
        #1;
        require(mixers_blank, "configuration update did not blank mixers");
        require(active_phase_codes == 8'h1B, "manual phase codes were not atomically applied");
        wait_for_unblank();

        channel_enable = 4'b0101;
        while (active_channel_enable != 4'b0101)
            @(posedge clk);
        #1;
        require(mixers_blank, "channel mask update did not blank mixers");
        wait_for_unblank();
        require((channel_lo_p & 4'b1010) == 4'b0000, "disabled P outputs toggled");
        require((channel_lo_n & 4'b1010) == 4'b0000, "disabled N outputs toggled");

        ena = 1'b0;
        repeat (3) @(posedge clk);
        #1;
        require(mixers_blank, "ena low did not blank mixers");
        require(channel_lo_p == 4'h0 && channel_lo_n == 4'h0, "LO outputs active while disabled");

        $display("PASS: quadrature, safe beam update, serial configuration, and channel masking");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "control-core testbench timeout");
    end

endmodule

`default_nettype wire
