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

    // The four-channel analog path, quadrature generator, beam decoder,
    // channel enables, and serial trim/phase configuration are implemented
    // physically in the custom GDS. Unused digital outputs must never float
    // into the shuttle fabric.
    assign uo_out  = 8'b0;
    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    // This file is the Tiny Tapeout black-box boundary contract. Keep all
    // physically consumed inputs and the two unavailable analog-template
    // shapes visible to lint without duplicating the GDS implementation.
    wire _unused = &{VGND, VDPWR, ui_in, uio_in, ua[7:6], ena, clk, rst_n, 1'b0};

endmodule

`default_nettype wire
