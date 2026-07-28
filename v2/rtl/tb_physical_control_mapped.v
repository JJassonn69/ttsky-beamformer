`timescale 1ns/1ps
`default_nettype none

module tb_physical_control_mapped;
    reg clk = 0, rst_n = 1, ena = 0;
    reg [1:0] beam_select = 0;
    reg manual_mode = 0;
    reg [3:0] channel_enable = 0;
    reg cfg_clk = 0, cfg_data = 0, cfg_latch = 0;
    wire [43:0] reference_outputs;
    wire [43:0] mapped_outputs;

    v2_physical_control_core reference (
        .clk(clk), .rst_n(rst_n), .ena(ena), .beam_select(beam_select),
        .manual_mode(manual_mode), .channel_enable(channel_enable),
        .cfg_clk(cfg_clk), .cfg_data(cfg_data), .cfg_latch(cfg_latch),
        .phase_wave(reference_outputs[43:40]),
        .phase_select0(reference_outputs[39:36]),
        .phase_select1(reference_outputs[35:32]),
        .phase_enable(reference_outputs[31:28]),
        .active_trim_codes(reference_outputs[27:12]),
        .active_phase_codes(reference_outputs[11:4]),
        .mixers_blank(reference_outputs[3])
    );
    assign reference_outputs[2:0] = 3'b0;

    v2_physical_control_core_mapped mapped (
        .clk(clk), .rst_n(rst_n), .ena(ena), .beam_select(beam_select),
        .manual_mode(manual_mode), .channel_enable(channel_enable),
        .cfg_clk(cfg_clk), .cfg_data(cfg_data), .cfg_latch(cfg_latch),
        .phase_wave(mapped_outputs[43:40]),
        .phase_select0(mapped_outputs[39:36]),
        .phase_select1(mapped_outputs[35:32]),
        .phase_enable(mapped_outputs[31:28]),
        .active_trim_codes(mapped_outputs[27:12]),
        .active_phase_codes(mapped_outputs[11:4]),
        .mixers_blank(mapped_outputs[3])
    );
    assign mapped_outputs[2:0] = 3'b0;

    always #31.25 clk = ~clk;

    task compare;
        begin
            #2;
            if (reference_outputs !== mapped_outputs) begin
                $display("FAIL reference=%h mapped=%h", reference_outputs, mapped_outputs);
                $display(
                    "mapped blank=%b direct_meta0=%b direct_sync0=%b andnot=%b blank_d=%b mux=%b phase=%b",
                    mapped.mapped_net_11, mapped.mapped_net_31,
                    mapped.mapped_net_39, mapped.mapped_net_59,
                    mapped.mapped_net_52, mapped.mapped_net_51, mapped.phase_wave
                );
                $fatal(1);
            end
        end
    endtask

    task shift_packet;
        input [23:0] packet;
        integer bit_index;
        begin
            for (bit_index = 0; bit_index < 24; bit_index = bit_index + 1) begin
                cfg_data = packet[bit_index];
                #10 cfg_clk = 1; #1; compare(); #7 cfg_clk = 0; compare();
            end
            cfg_latch = 1;
            #10 cfg_clk = 1; #1; compare(); #7 cfg_clk = 0; compare();
            cfg_latch = 0;
        end
    endtask

    integer cycle;
    initial begin
        #1 rst_n = 0; compare();
        repeat (3) begin @(posedge clk); compare(); end
        rst_n = 1; ena = 1; channel_enable = 4'hf;
        for (cycle = 0; cycle < 80; cycle = cycle + 1) begin
            @(posedge clk); compare();
            if (cycle == 12) beam_select = 2'd1;
            if (cycle == 28) beam_select = 2'd3;
            if (cycle == 44) channel_enable = 4'b0101;
        end
        manual_mode = 1;
        shift_packet({8'he4, 16'h8421});
        repeat (40) begin @(posedge clk); compare(); end
        rst_n = 0; compare();
        @(posedge clk); compare();
        rst_n = 1;
        repeat (16) begin @(posedge clk); compare(); end
        $display("PASS: mapped SKY130 control netlist is cycle-equivalent to RTL");
        $finish;
    end
endmodule

`default_nettype wire
