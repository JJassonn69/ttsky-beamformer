`timescale 1ns/1ps
`default_nettype none

module tb_physical_control_core;
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
    wire [3:0] phase_select0;
    wire [3:0] phase_select1;
    wire [3:0] phase_enable;
    wire [15:0] active_trim_codes;
    wire [7:0] active_phase_codes;
    wire mixers_blank;

    v2_physical_control_core dut (
        .clk(clk), .rst_n(rst_n), .ena(ena),
        .beam_select(beam_select), .manual_mode(manual_mode),
        .channel_enable(channel_enable),
        .cfg_clk(cfg_clk), .cfg_data(cfg_data), .cfg_latch(cfg_latch),
        .phase_wave(phase_wave), .phase_select0(phase_select0),
        .phase_select1(phase_select1), .phase_enable(phase_enable),
        .active_trim_codes(active_trim_codes),
        .active_phase_codes(active_phase_codes), .mixers_blank(mixers_blank)
    );

    always #31.25 clk = ~clk;

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
            while (mixers_blank && cycles < 32) begin
                @(posedge clk); #1; cycles = cycles + 1;
            end
            require(!mixers_blank, "mixers did not unblank");
        end
    endtask

    task shift_physical_config;
        input [23:0] value;
        integer bit_index;
        begin
            // value[15:0] is trim; value[23:16] is manual phase.
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

    integer channel;
    reg [23:0] packet;
    initial begin
        #1 rst_n = 1'b0;
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        ena = 1'b1;
        wait_for_unblank();
        while (active_phase_codes != 8'h00 || phase_enable != 4'hF)
            @(posedge clk);
        wait_for_unblank();

        beam_select = 2'd1;
        @(posedge mixers_blank);
        wait_for_unblank();
        require(active_phase_codes == 8'h6C, "beam one is not RX-conjugate 0,3,2,1");

        beam_select = 2'd3;
        @(posedge mixers_blank);
        wait_for_unblank();
        require(active_phase_codes == 8'hE4, "beam three is not RX-conjugate 0,1,2,3");

        // Trim CH3..CH0 = 8,4,2,1; phase CH3..CH0 = 3,2,1,0.
        packet = {8'hE4, 16'h8421};
        manual_mode = 1'b1;
        shift_physical_config(packet);
        @(posedge mixers_blank);
        wait_for_unblank();
        require(active_phase_codes == 8'hE4, "manual phase chunks mapped to wrong channels");
        require(active_trim_codes == 16'h8421, "trim chunks mapped to wrong channels");
        require(phase_select0 == 4'b1010, "selector bit zero mapping is wrong");
        require(phase_select1 == 4'b1100, "selector bit one mapping is wrong");

        channel_enable = 4'b0101;
        @(posedge mixers_blank);
        wait_for_unblank();
        require(phase_enable == 4'b0101, "local enable mask is wrong");

        for (channel = 0; channel < 4; channel = channel + 1)
            require(
                active_phase_codes[2*channel +: 2]
                    == {phase_select1[channel], phase_select0[channel]},
                "phase code disagrees with local selector wires"
            );

        $display("PASS: physical RX codebook, partitioned config chain, local controls, and safe blanking");
        $finish;
    end

    initial begin
        #120000;
        $fatal(1, "physical-control testbench timeout");
    end
endmodule

`default_nettype wire
