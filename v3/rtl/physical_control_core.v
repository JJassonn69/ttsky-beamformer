`default_nettype none

// Physical configuration storage keeps the 32-bit serial shift chain and the
// 32-bit active code bank together in the quiet control region.  Only the
// active bank fans out to the four local selector macros.
(* keep_hierarchy *) module v3_physical_config_storage #(
    parameter integer WIDTH = 32,
    parameter [WIDTH-1:0] RESET_VALUE = {WIDTH{1'b0}}
) (
    input  wire                 cfg_clk,
    input  wire                 cfg_data,
    input  wire                 cfg_latch,
    input  wire                 apply_config,
    input  wire                 clk,
    input  wire                 rst_n,
    output wire [WIDTH-1:0]     active_data
);
    reg [WIDTH-1:0] shift_bits;
    reg [WIDTH-1:0] active_bits;

    always @(posedge cfg_clk or negedge rst_n) begin
        if (!rst_n)
            shift_bits <= RESET_VALUE;
        else if (!cfg_latch)
            shift_bits <= {cfg_data, shift_bits[WIDTH-1:1]};
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            active_bits <= RESET_VALUE;
        else if (apply_config)
            active_bits <= shift_bits;
    end

    assign active_data = active_bits;
endmodule


// Layout-oriented V3 controller.  Phase selection remains inside each frozen
// analog channel macro, so this block exports static two-bit group codes rather
// than duplicating 32 phase-selection cones in the central digital region.
module v3_physical_control_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        ena,
    input  wire [2:0]  beam_select,
    input  wire        raw_mode,
    input  wire [3:0]  channel_enable,
    input  wire        cfg_clk,
    input  wire        cfg_data,
    input  wire        cfg_latch,
    output wire [3:0]  phase_wave,
    output wire [31:0] group_codes,
    output wire [3:0]  channel_bias_enable,
    output wire        mixers_blank
);
    localparam [31:0] CONFIG_RESET = 32'h08080808;

    reg [8:0] direct_meta;
    reg [8:0] direct_sync;
    wire [8:0] direct_async = {
        channel_enable,
        raw_mode,
        beam_select,
        ena
    };

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            direct_meta <= 9'h000;
            direct_sync <= 9'h000;
        end else begin
            direct_meta <= direct_async;
            direct_sync <= direct_meta;
        end
    end

    wire       ena_sync = direct_sync[0];
    wire [2:0] beam_sync = direct_sync[3:1];
    wire       raw_sync = direct_sync[4];
    wire [3:0] channel_enable_sync = direct_sync[8:5];

    reg cfg_commit_toggle;
    always @(posedge cfg_clk or negedge rst_n) begin
        if (!rst_n)
            cfg_commit_toggle <= 1'b0;
        else if (cfg_latch)
            cfg_commit_toggle <= ~cfg_commit_toggle;
    end

    reg cfg_toggle_meta;
    reg cfg_toggle_sync;
    reg cfg_toggle_seen;
    reg cfg_pending;
    reg [2:0] active_beam;
    reg active_raw_mode;
    reg [3:0] active_channel_enable;
    reg blank_reg;
    wire [1:0] phase_state;
    wire safe_boundary = phase_state == 2'b10;
    wire direct_update_needed = active_beam != beam_sync
        || active_raw_mode != raw_sync
        || active_channel_enable != channel_enable_sync;
    wire update_boundary = safe_boundary && !blank_reg
        && (cfg_pending || direct_update_needed);
    wire apply_config = update_boundary && cfg_pending;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_toggle_meta <= 1'b0;
            cfg_toggle_sync <= 1'b0;
            cfg_toggle_seen <= 1'b0;
            cfg_pending <= 1'b0;
        end else begin
            cfg_toggle_meta <= cfg_commit_toggle;
            cfg_toggle_sync <= cfg_toggle_meta;
            if (cfg_toggle_sync != cfg_toggle_seen) begin
                cfg_toggle_seen <= cfg_toggle_sync;
                cfg_pending <= 1'b1;
            end else if (apply_config) begin
                cfg_pending <= 1'b0;
            end
        end
    end

    v3_quadrature_generator quadrature_generator (
        .clk(clk),
        .rst_n(rst_n),
        .enable(ena_sync),
        .state(phase_state),
        .phase(phase_wave)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active_beam <= 3'd0;
            active_raw_mode <= 1'b0;
            active_channel_enable <= 4'h0;
            blank_reg <= 1'b1;
        end else if (!ena_sync) begin
            active_channel_enable <= 4'h0;
            blank_reg <= 1'b1;
        end else if (blank_reg) begin
            if (safe_boundary)
                blank_reg <= 1'b0;
        end else if (update_boundary) begin
            active_beam <= beam_sync;
            active_raw_mode <= raw_sync;
            active_channel_enable <= channel_enable_sync;
            blank_reg <= 1'b1;
        end
    end

    wire [31:0] active_raw_words;
    v3_physical_config_storage #(
        .WIDTH(32),
        .RESET_VALUE(CONFIG_RESET)
    ) config_storage (
        .cfg_clk(cfg_clk),
        .cfg_data(cfg_data),
        .cfg_latch(cfg_latch),
        .apply_config(apply_config),
        .clk(clk),
        .rst_n(rst_n),
        .active_data(active_raw_words)
    );

    function [31:0] automatic_beam_words;
        input [2:0] beam;
        begin
            case (beam)
                3'd0: automatic_beam_words = 32'h08080808;
                3'd1: automatic_beam_words = 32'hBFF7C008;
                3'd2: automatic_beam_words = 32'h5DA2F708;
                3'd3: automatic_beam_words = 32'hC05DBF08;
                3'd4: automatic_beam_words = 32'hA208A208;
                3'd5: automatic_beam_words = 32'h15F76A08;
                3'd6: automatic_beam_words = 32'hF7A25D08;
                3'd7: automatic_beam_words = 32'h6A5D1508;
                default: automatic_beam_words = CONFIG_RESET;
            endcase
        end
    endfunction

    assign group_codes = active_raw_mode
        ? active_raw_words
        : automatic_beam_words(active_beam);
    assign mixers_blank = blank_reg || !ena_sync;
    assign channel_bias_enable = active_channel_enable
        & {4{!mixers_blank}};
endmodule

`default_nettype wire
