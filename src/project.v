/*
 * Copyright (c) 2026 Jason
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_jjassonn69_beamformer (
    input  wire       VGND,
    input  wire       VDPWR,
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    inout  wire [7:0] ua,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    // The analog implementation and CH2_PHASE_180 routing are in the custom
    // GDS. Unused digital outputs must never float into the shuttle fabric.
    assign uo_out  = 8'b0;
    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    // Keep boundary-only inputs visible to lint without creating logic.
    wire _unused = &{VGND, VDPWR, ui_in[7:1], uio_in, ua[7:4], ena, clk, rst_n, 1'b0};

endmodule

`default_nettype wire
