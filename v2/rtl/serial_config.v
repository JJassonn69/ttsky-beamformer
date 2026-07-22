`default_nettype none

// LSB-first serial register. cfg_latch is asserted for one cfg_clk edge after
// all WIDTH bits have been shifted. committed_data then remains stable until
// the next commit, allowing a toggle-based multi-bit CDC into the master clock.
module v2_serial_config #(
    parameter integer WIDTH = 24,
    parameter [WIDTH-1:0] RESET_VALUE = {WIDTH{1'b0}}
) (
    input  wire                 cfg_clk,
    input  wire                 cfg_data,
    input  wire                 cfg_latch,
    input  wire                 rst_n,
    output reg  [WIDTH-1:0]     committed_data,
    output reg                  commit_toggle
);

    reg [WIDTH-1:0] shift_data;

    always @(posedge cfg_clk or negedge rst_n) begin
        if (!rst_n) begin
            shift_data     <= RESET_VALUE;
            committed_data <= RESET_VALUE;
            commit_toggle  <= 1'b0;
        end else begin
            shift_data <= {cfg_data, shift_data[WIDTH-1:1]};
            if (cfg_latch) begin
                committed_data <= shift_data;
                commit_toggle  <= ~commit_toggle;
            end
        end
    end

endmodule

`default_nettype wire
