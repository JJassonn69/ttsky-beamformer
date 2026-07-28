`timescale 1ns/1ps
`default_nettype none

module tb_physical_control_core;
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
    wire [31:0] group_codes;
    wire [3:0] channel_bias_enable;
    wire mixers_blank;

    v3_physical_control_core dut (
        .clk(clk), .rst_n(rst_n), .ena(ena),
        .beam_select(beam_select), .raw_mode(raw_mode),
        .channel_enable(channel_enable), .cfg_clk(cfg_clk),
        .cfg_data(cfg_data), .cfg_latch(cfg_latch),
        .phase_wave(phase_wave), .group_codes(group_codes),
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
            while (mixers_blank && cycles < 40) begin
                @(posedge clk);
                #1;
                cycles = cycles + 1;
            end
            require(!mixers_blank, "physical controller did not unblank");
        end
    endtask

    task wait_for_code;
        input [31:0] expected;
        integer cycles;
        begin
            cycles = 0;
            while ((group_codes !== expected || mixers_blank) && cycles < 80) begin
                @(posedge clk);
                #1;
                cycles = cycles + 1;
            end
            require(group_codes === expected, "group-code update missed safe boundary");
            require(!mixers_blank, "group-code update never completed blanking");
        end
    endtask

    task wait_for_bias_mask;
        input [3:0] expected;
        integer cycles;
        begin
            cycles = 0;
            while ((channel_bias_enable !== expected || mixers_blank) && cycles < 80) begin
                @(posedge clk);
                #1;
                cycles = cycles + 1;
            end
            require(channel_bias_enable === expected, "channel-enable update missed safe boundary");
            require(!mixers_blank, "channel-enable update never completed blanking");
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

    initial begin
        #2 rst_n = 1'b0;
        #20 rst_n = 1'b1;
        #10 ena = 1'b1;
        wait_for_unblank();
        wait_for_bias_mask(4'hF);
        require(group_codes === 32'h08080808, "reset/default beam word mismatch");
        require(channel_bias_enable === 4'hF, "enabled channels did not reach bias gates");

        beam_select = 3'd1;
        wait_for_code(32'hBFF7C008);

        shift_config(32'hA53CC35A);
        raw_mode = 1'b1;
        wait_for_code(32'hA53CC35A);

        channel_enable = 4'b0101;
        wait_for_bias_mask(4'b0101);

        ena = 1'b0;
        repeat (4) @(posedge clk);
        #1;
        require(mixers_blank, "disable did not blank mixers");
        require(channel_bias_enable === 4'h0, "disable left a channel bias enabled");
        $display("PASS: V3 physical-control behavior and 32-bit serial update");
        $finish;
    end
endmodule

`default_nettype wire
