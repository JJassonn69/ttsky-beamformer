`default_nettype none

// Functional models for the exact drive-1 SKY130 cells used by the generated
// physical control netlist.  These models are for logic equivalence only;
// transistor SPICE and extracted interconnect are used for timing/parasitics.
module sky130_fd_sc_hd__inv_1(input wire A, output wire Y, input wire VPWR, VGND);
    assign Y = ~A;
endmodule
module sky130_fd_sc_hd__and2_1(input wire A, B, output wire X, input wire VPWR, VGND);
    assign X = A & B;
endmodule
module sky130_fd_sc_hd__and2b_1(input wire A_N, B, output wire X, input wire VPWR, VGND);
    assign X = ~A_N & B;
endmodule
module sky130_fd_sc_hd__or2_1(input wire A, B, output wire X, input wire VPWR, VGND);
    assign X = A | B;
endmodule
module sky130_fd_sc_hd__or2b_1(input wire A, B_N, output wire X, input wire VPWR, VGND);
    assign X = A | ~B_N;
endmodule
module sky130_fd_sc_hd__nand2_1(input wire A, B, output wire Y, input wire VPWR, VGND);
    assign Y = ~(A & B);
endmodule
module sky130_fd_sc_hd__nor2_1(input wire A, B, output wire Y, input wire VPWR, VGND);
    assign Y = ~(A | B);
endmodule
module sky130_fd_sc_hd__xor2_1(input wire A, B, output wire X, input wire VPWR, VGND);
    assign X = A ^ B;
endmodule
module sky130_fd_sc_hd__mux2_1(input wire A0, A1, S, output wire X, input wire VPWR, VGND);
    assign X = S ? A1 : A0;
endmodule
module sky130_fd_sc_hd__dfrtp_1(
    input wire D, RESET_B, CLK, output reg Q, input wire VPWR, VGND
);
    always @(posedge CLK or negedge RESET_B)
        if (!RESET_B) Q <= 1'b0; else Q <= D;
endmodule
module sky130_fd_sc_hd__dfstp_1(
    input wire D, SET_B, CLK, output reg Q, input wire VPWR, VGND
);
    always @(posedge CLK or negedge SET_B)
        if (!SET_B) Q <= 1'b1; else Q <= D;
endmodule

`default_nettype wire
