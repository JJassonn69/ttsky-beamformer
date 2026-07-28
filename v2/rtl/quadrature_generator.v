`default_nettype none

// Four 50%-duty-cycle phases from a master clock at four times the LO rate.
// The two-bit Johnson sequence changes only one state bit per master edge:
//   00 -> 01 -> 11 -> 10 -> 00
module v2_quadrature_generator (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       enable,
    output reg  [1:0] state,
    output wire [3:0] phase
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= 2'b00;
        else if (!enable)
            state <= 2'b00;
        else
            state <= {state[0], ~state[1]};
    end

    // phase[0:3] correspond to nominal 0, 90, 180 and 270 degrees.
    assign phase[0] = ~state[1];
    assign phase[1] =  state[0];
    assign phase[2] =  state[1];
    assign phase[3] = ~state[0];

endmodule

`default_nettype wire
