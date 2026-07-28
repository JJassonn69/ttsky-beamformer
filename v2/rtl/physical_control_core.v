`default_nettype none

// Configuration storage is split by physical destination.  The eight phase
// bits stay above the selectors, while the sixteen trim bits sit in the quiet
// support region beside the bottom trim-control rows.  Only one serial link
// joins the banks; the 24 parallel data wires never cross the macro.
(* keep_hierarchy *) module v2_config_storage #(
    parameter integer WIDTH = 8,
    parameter [WIDTH-1:0] RESET_VALUE = {WIDTH{1'b0}}
) (
    input  wire                 cfg_clk,
    input  wire                 cfg_data,
    input  wire                 cfg_latch,
    input  wire                 apply_config,
    input  wire                 clk,
    input  wire                 rst_n,
    output wire                 cfg_data_out,
    output wire [WIDTH-1:0]     active_data
);
    reg [WIDTH-1:0] shift_bits;
    reg [WIDTH-1:0] active_bits;

    // The latch edge does not shift.  This matters because active_bits samples
    // shift_bits later in the master-clock domain, after the commit toggle has
    // crossed its two-flop synchronizer.
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

    assign cfg_data_out = shift_bits[0];
    assign active_data = active_bits;
endmodule


// Physical-control boundary for the custom analog layout.  Phase selection,
// complementary P/N generation, blanking gates, and final buffers are already
// instantiated beside each analog channel; this core only supplies their
// short local control wires and the four balanced global phase roots.
module v2_physical_control_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        ena,
    input  wire [1:0]  beam_select,
    input  wire        manual_mode,
    input  wire [3:0]  channel_enable,
    input  wire        cfg_clk,
    input  wire        cfg_data,
    input  wire        cfg_latch,
    output wire [3:0]  phase_wave,
    output wire [3:0]  phase_select0,
    output wire [3:0]  phase_select1,
    output wire [3:0]  phase_enable,
    output wire [15:0] active_trim_codes,
    output wire [7:0]  active_phase_codes,
    output wire        mixers_blank
);
    reg [7:0] direct_meta;
    reg [7:0] direct_sync;
    wire [7:0] direct_async = {
        channel_enable,
        manual_mode,
        beam_select,
        ena
    };

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            direct_meta <= 8'h00;
            direct_sync <= 8'h00;
        end else begin
            direct_meta <= direct_async;
            direct_sync <= direct_meta;
        end
    end

    wire       ena_sync = direct_sync[0];
    wire [1:0] beam_sync = direct_sync[2:1];
    wire       manual_sync = direct_sync[3];
    wire [3:0] channel_enable_sync = direct_sync[7:4];

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
    reg [1:0] active_beam;
    reg active_manual;
    reg [3:0] active_channel_enable;
    reg blank_reg;
    wire [1:0] phase_state;
    wire direct_update_needed = active_beam != beam_sync
        || active_manual != manual_sync
        || active_channel_enable != channel_enable_sync;
    wire safe_boundary = phase_state == 2'b10;
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

    v2_quadrature_generator quadrature_generator (
        .clk(clk),
        .rst_n(rst_n),
        .enable(ena_sync),
        .state(phase_state),
        .phase(phase_wave)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active_beam <= 2'b00;
            active_manual <= 1'b0;
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
            active_manual <= manual_sync;
            active_channel_enable <= channel_enable_sync;
            blank_reg <= 1'b1;
        end
    end

    wire serial_phase_to_trim;
    wire serial_unused;
    wire [7:0] manual_phase_codes;

    // Physical packet, LSB first: trim[15:0], then manual_phase[7:0].
    // The most recent eight bits remain in the top phase bank; the first
    // sixteen propagate over one serial wire to the lower-right trim bank.
    v2_config_storage #(.WIDTH(8), .RESET_VALUE(8'h00)) phase_config (
        .cfg_clk(cfg_clk), .cfg_data(cfg_data), .cfg_latch(cfg_latch),
        .apply_config(apply_config), .clk(clk), .rst_n(rst_n),
        .cfg_data_out(serial_phase_to_trim), .active_data(manual_phase_codes)
    );
    v2_config_storage #(.WIDTH(16), .RESET_VALUE(16'h8888)) trim_config (
        .cfg_clk(cfg_clk), .cfg_data(serial_phase_to_trim),
        .cfg_latch(cfg_latch), .apply_config(apply_config),
        .clk(clk), .rst_n(rst_n), .cfg_data_out(serial_unused),
        .active_data(active_trim_codes)
    );

    function [1:0] rx_phase_code;
        input [1:0] beam;
        input [1:0] channel;
        begin
            case (channel)
                2'd0: rx_phase_code = 2'b00;
                2'd1: rx_phase_code = -beam;
                2'd2: rx_phase_code = {beam[0], 1'b0};
                // -3*beam modulo four is identical to +beam.
                2'd3: rx_phase_code = beam;
                default: rx_phase_code = 2'b00;
            endcase
        end
    endfunction

    genvar channel_index;
    generate
        for (channel_index = 0; channel_index < 4; channel_index = channel_index + 1) begin : controls
            wire [1:0] automatic_code = rx_phase_code(active_beam, channel_index);
            wire [1:0] selected_code = active_manual
                ? manual_phase_codes[2*channel_index +: 2]
                : automatic_code;
            assign active_phase_codes[2*channel_index +: 2] = selected_code;
            assign phase_select0[channel_index] = selected_code[0];
            assign phase_select1[channel_index] = selected_code[1];
            assign phase_enable[channel_index] = active_channel_enable[channel_index]
                && !blank_reg && ena_sync;
        end
    endgenerate

    assign mixers_blank = blank_reg || !ena_sync;
    wire _unused = serial_unused;
endmodule

`default_nettype wire
