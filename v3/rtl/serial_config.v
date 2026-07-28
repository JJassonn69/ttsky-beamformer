`default_nettype none

// LSB-first 32-bit coefficient register. The committed bus remains stable
// while its toggle crosses into the 16 MHz master-clock domain.
module v3_serial_config #(
    parameter integer WIDTH = 32,
    parameter [WIDTH-1:0] RESET_VALUE = {WIDTH{1'b0}}
) (
    input  wire             cfg_clk,
    input  wire             cfg_data,
    input  wire             cfg_latch,
    input  wire             rst_n,
    output reg  [WIDTH-1:0] committed_data,
    output reg              commit_toggle
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
