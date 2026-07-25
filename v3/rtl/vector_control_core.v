`default_nettype none

module v3_vector_control_core (
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
    output wire [15:0] group_lo_p,
    output wire [15:0] group_lo_n,
    output reg  [31:0] active_vector_words,
    output reg  [3:0]  active_channel_enable,
    output wire [3:0]  channel_bias_enable,
    output wire        mixers_blank
);

    localparam [31:0] CONFIG_RESET = 32'h08080808;

    wire [31:0] cfg_committed_async;
    wire        cfg_commit_toggle_async;
    v3_serial_config #(
        .WIDTH(32),
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
    v3_quadrature_generator quadrature_generator (
        .clk(clk),
        .rst_n(rst_n),
        .enable(ena),
        .state(phase_state),
        .phase(phase_wave)
    );

    // Direct controls are static configuration and receive two synchronizer
    // stages before they influence any analog control.
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

    // Stable multi-bit bus plus toggle CDC, inherited from V2.
    reg cfg_toggle_meta;
    reg cfg_toggle_sync;
    reg cfg_toggle_seen;
    reg [31:0] cfg_pending_data;
    reg cfg_pending_valid;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_toggle_meta   <= 1'b0;
            cfg_toggle_sync   <= 1'b0;
            cfg_toggle_seen   <= 1'b0;
            cfg_pending_data  <= CONFIG_RESET;
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

    // Packed little-endian by channel: CH0 is bits 7:0 and CH3 is 31:24.
    // Values are generated from v3/model/beamformer_v3.py. Four even beams
    // retain the legacy DFT directions; odd beams are intermediate steering.
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

    reg [31:0] stored_raw_words;
    reg blank_reg;

    wire [31:0] desired_raw_words = cfg_pending_valid
        ? cfg_pending_data
        : stored_raw_words;
    wire [31:0] desired_vector_words = raw_sync
        ? desired_raw_words
        : automatic_beam_words(beam_sync);
    wire update_needed = cfg_pending_valid
        || desired_vector_words != active_vector_words
        || channel_enable_sync != active_channel_enable;

    // Commit immediately before the Johnson counter returns to phase zero,
    // then blank LO and tail enables for one complete LO period. Gate 2C must
    // confirm that one period is sufficient analog settling before layout.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stored_raw_words       <= CONFIG_RESET;
            active_vector_words    <= CONFIG_RESET;
            active_channel_enable  <= 4'h0;
            blank_reg              <= 1'b1;
        end else if (!ena_sync) begin
            active_channel_enable <= 4'h0;
            blank_reg             <= 1'b1;
        end else if (blank_reg) begin
            if (phase_state == 2'b10)
                blank_reg <= 1'b0;
        end else if (phase_state == 2'b10 && update_needed) begin
            stored_raw_words      <= desired_raw_words;
            active_vector_words   <= desired_vector_words;
            active_channel_enable <= channel_enable_sync;
            blank_reg             <= 1'b1;
        end
    end

    assign mixers_blank = blank_reg || !ena_sync;
    assign channel_bias_enable = active_channel_enable & {4{!mixers_blank}};

    genvar group_index;
    generate
        for (group_index = 0; group_index < 16; group_index = group_index + 1) begin : group_selectors
            wire [1:0] axis_code = active_vector_words[2*group_index +: 2];
            wire selected_p = axis_code == 2'd0 ? phase_wave[0]
                : axis_code == 2'd1 ? phase_wave[1]
                : axis_code == 2'd2 ? phase_wave[2]
                : phase_wave[3];
            wire group_enabled = active_channel_enable[group_index / 4]
                && !mixers_blank;
            assign group_lo_p[group_index] = selected_p && group_enabled;
            assign group_lo_n[group_index] = !selected_p && group_enabled;
        end
    endgenerate

endmodule

`default_nettype wire
