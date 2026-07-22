`default_nettype none

module v2_control_core (
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
    output wire [3:0]  channel_lo_p,
    output wire [3:0]  channel_lo_n,
    output reg  [7:0]  active_phase_codes,
    output reg  [15:0] active_trim_codes,
    output reg  [3:0]  active_channel_enable,
    output wire        mixers_blank
);

    localparam [23:0] CONFIG_RESET = {
        16'h8888, // four nominal gain-trim codes
        8'h00     // four manual zero-degree phase codes
    };

    wire [23:0] cfg_committed_async;
    wire        cfg_commit_toggle_async;

    v2_serial_config #(
        .WIDTH(24),
        .RESET_VALUE(CONFIG_RESET)
    ) config_register (
        .cfg_clk(cfg_clk),
        .cfg_data(cfg_data),
        .cfg_latch(cfg_latch),
        .rst_n(rst_n),
        .committed_data(cfg_committed_async),
        .commit_toggle(cfg_commit_toggle_async)
    );

    reg [1:0] phase_state;
    v2_quadrature_generator quadrature_generator (
        .clk(clk),
        .rst_n(rst_n),
        .enable(ena),
        .state(phase_state),
        .phase(phase_wave)
    );

    // Synchronize direct controls. They are treated as static configuration,
    // not cycle-by-cycle data.
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

    // Toggle synchronizer for the stable multi-bit configuration bus.
    reg cfg_toggle_meta;
    reg cfg_toggle_sync;
    reg cfg_toggle_seen;
    reg [23:0] cfg_pending_data;
    reg cfg_pending_valid;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_toggle_meta  <= 1'b0;
            cfg_toggle_sync  <= 1'b0;
            cfg_toggle_seen  <= 1'b0;
            cfg_pending_data <= CONFIG_RESET;
            cfg_pending_valid <= 1'b0;
        end else begin
            cfg_toggle_meta <= cfg_commit_toggle_async;
            cfg_toggle_sync <= cfg_toggle_meta;
            if (cfg_toggle_sync != cfg_toggle_seen) begin
                cfg_toggle_seen   <= cfg_toggle_sync;
                cfg_pending_data  <= cfg_committed_async;
                cfg_pending_valid <= 1'b1;
            end else if (cfg_pending_valid && phase_state == 2'b10) begin
                cfg_pending_valid <= 1'b0;
            end
        end
    end

    function [7:0] codebook_phase_codes;
        input [1:0] beam;
        begin
            case (beam)
                2'd0: codebook_phase_codes = 8'h00; // 0,0,0,0
                2'd1: codebook_phase_codes = 8'h6C; // RX: 0,3,2,1
                2'd2: codebook_phase_codes = 8'h88; // 0,2,0,2
                2'd3: codebook_phase_codes = 8'hE4; // RX: 0,1,2,3
                default: codebook_phase_codes = 8'h00;
            endcase
        end
    endfunction

    reg [7:0] stored_manual_phase_codes;
    reg blank_reg;

    wire [7:0] desired_manual_codes = cfg_pending_valid
        ? cfg_pending_data[7:0]
        : stored_manual_phase_codes;
    wire [15:0] desired_trim_codes = cfg_pending_valid
        ? cfg_pending_data[23:8]
        : active_trim_codes;
    wire [7:0] desired_phase_codes = manual_sync
        ? desired_manual_codes
        : codebook_phase_codes(beam_sync);
    wire update_needed = cfg_pending_valid
        || desired_phase_codes != active_phase_codes
        || channel_enable_sync != active_channel_enable;

    // phase_state=10 is the state immediately before the Johnson counter
    // returns to 00. Commit there, then blank exactly one complete LO period.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stored_manual_phase_codes <= 8'h00;
            active_phase_codes        <= 8'h00;
            active_trim_codes         <= 16'h8888;
            active_channel_enable     <= 4'h0;
            blank_reg                 <= 1'b1;
        end else if (!ena_sync) begin
            active_channel_enable <= 4'h0;
            blank_reg             <= 1'b1;
        end else if (blank_reg) begin
            if (phase_state == 2'b10)
                blank_reg <= 1'b0;
        end else if (phase_state == 2'b10 && update_needed) begin
            stored_manual_phase_codes <= desired_manual_codes;
            active_phase_codes        <= desired_phase_codes;
            active_trim_codes         <= desired_trim_codes;
            active_channel_enable     <= channel_enable_sync;
            blank_reg                 <= 1'b1;
        end
    end

    assign mixers_blank = blank_reg || !ena_sync;

    genvar channel_index;
    generate
        for (channel_index = 0; channel_index < 4; channel_index = channel_index + 1) begin : phase_selectors
            wire [1:0] phase_code = active_phase_codes[2*channel_index +: 2];
            reg selected_p;
            always @(*) begin
                case (phase_code)
                    2'd0: selected_p = phase_wave[0];
                    2'd1: selected_p = phase_wave[1];
                    2'd2: selected_p = phase_wave[2];
                    2'd3: selected_p = phase_wave[3];
                    default: selected_p = 1'b0;
                endcase
            end
            assign channel_lo_p[channel_index] = selected_p
                && active_channel_enable[channel_index]
                && !mixers_blank;
            assign channel_lo_n[channel_index] = !selected_p
                && active_channel_enable[channel_index]
                && !mixers_blank;
        end
    endgenerate

endmodule

`default_nettype wire
