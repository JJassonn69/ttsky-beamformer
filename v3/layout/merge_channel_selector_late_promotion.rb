# Merge the connected channel and late-root selector with eight matched joins.
require "json"
include RBA

root = File.expand_path(ENV.fetch("V3_PROJECT_ROOT"))
channel_gds = File.expand_path(ENV.fetch("V3_CHANNEL_GDS"))
selector_gds = File.expand_path(ENV.fetch("V3_SELECTOR_GDS"))
output_gds = File.expand_path(ENV.fetch("V3_JOINED_GDS"))
manifest = JSON.parse(File.read(File.join(root, "v3/layout/channel_selector_join_late_promotion.json")))

layout = Layout.new
layout.read(channel_gds)
layout.read(selector_gds)
channel = layout.cell("v3_channel_input_bias_late_promotion")
selector = layout.cell("v3_selector_route_pilot")
tap_cell = layout.cell("sky130_fd_sc_hd__tapvpwrvgnd_1")
raise "channel top missing" if channel.nil?
raise "selector top missing" if selector.nil?
raise "selector tap cell missing" if tap_cell.nil?
top = layout.create_cell("v3_channel_selector_late_promotion")
top.insert(CellInstArray.new(channel.cell_index, Trans.new))
origin = manifest.fetch("selector_instance_origin_um")
top.insert(CellInstArray.new(selector.cell_index, Trans.new((origin[0] / layout.dbu).round, (origin[1] / layout.dbu).round)))

# The uppermost N-oriented row has no following mirrored row from which to
# inherit a well tap.  Place one physical-only tap in the free site directly
# after the final logic cell; its abutted LI/M1 rails join the selector rails.
well_tap = manifest.fetch("selector_power").fetch("top_row_well_tap")
raise "unsupported well-tap orientation" unless well_tap.fetch("orientation") == "N"
tap_origin = well_tap.fetch("origin_um")
top.insert(CellInstArray.new(
  tap_cell.cell_index,
  Trans.new(
    ((origin[0] + tap_origin[0]) / layout.dbu).round,
    ((origin[1] + tap_origin[1]) / layout.dbu).round,
  ),
))

layers = {
  "metal1" => layout.layer(LayerInfo.new(68, 20)),
  "via1" => layout.layer(LayerInfo.new(68, 44)),
  "metal2" => layout.layer(LayerInfo.new(69, 20)),
  "via2" => layout.layer(LayerInfo.new(69, 44)),
  "metal3" => layout.layer(LayerInfo.new(70, 20)),
  "via3" => layout.layer(LayerInfo.new(70, 44)),
  "metal4" => layout.layer(LayerInfo.new(71, 20)),
  "metal2_label" => layout.layer(LayerInfo.new(69, 5)),
  "metal3_label" => layout.layer(LayerInfo.new(70, 5)),
  "metal4_label" => layout.layer(LayerInfo.new(71, 5)),
}
channel_origin = manifest.fetch("channel_gds_origin_um")
dbu = layout.dbu
box = lambda do |layer_name, x1, y1, x2, y2|
  top.shapes(layers.fetch(layer_name)).insert(Box.new((x1 / dbu).round, (y1 / dbu).round, (x2 / dbu).round, (y2 / dbu).round))
end

manifest.fetch("joins").each do |join|
  x = channel_origin[0] + join.fetch("x_um")
  selector_y = channel_origin[1] + join.fetch("selector_pin_center_y_um")
  transition_y = channel_origin[1] + join.fetch("transition_y_um")
  root_y = channel_origin[1] + join.fetch("analog_root_y_um")
  box.call("metal2", x - 0.15, transition_y, x + 0.15, selector_y + 0.20)
  box.call("metal4", x - 0.20, root_y - 0.20, x + 0.20, transition_y)
  box.call("metal2", x - 0.20, transition_y - 0.20, x + 0.20, transition_y + 0.20)
  box.call("via2", x - 0.10, transition_y - 0.10, x + 0.10, transition_y + 0.10)
  box.call("metal3", x - 0.31, transition_y - 0.20, x + 0.31, transition_y + 0.20)
  box.call("via3", x - 0.10, transition_y - 0.10, x + 0.10, transition_y + 0.10)
  box.call("metal4", x - 0.20, transition_y - 0.20, x + 0.20, transition_y + 0.20)
end

# Two independent M4 straps tap the alternating standard-cell rails.  The
# selector's routed signal network uses no M4, so this avoids both hidden
# power/signal shorts and unnecessary disturbance of its closed M1--M3 route.
power = manifest.fetch("selector_power")
selector_origin = manifest.fetch("selector_instance_origin_um")
tap_x = selector_origin[0] + power.fetch("rail_tap_x_um")
vpwr_x = selector_origin[0] + power.fetch("vpwr_strap_x_um")
vgnd_x = selector_origin[0] + power.fetch("vgnd_strap_x_um")
width = power.fetch("strap_width_um")
half = width / 2.0
vpwr_ys = power.fetch("vpwr_rail_y_um").map { |y| selector_origin[1] + y }
vgnd_ys = power.fetch("vgnd_rail_y_um").map { |y| selector_origin[1] + y }
box.call("metal4", vpwr_x - half, vpwr_ys.min - half, vpwr_x + half, vpwr_ys.max + half)
box.call("metal4", vgnd_x - half, power.fetch("vgnd_guard_join_y_absolute_um") - 0.30, vgnd_x + half, vgnd_ys.max + half)
{
  "VPWR" => [vpwr_x, vpwr_ys],
  "VGND" => [vgnd_x, vgnd_ys],
}.each do |_name, values|
  strap_x, rail_ys = values
  rail_ys.each do |y|
    box.call("metal1", tap_x - 0.16, y - 0.16, tap_x + 0.16, y + 0.16)
    box.call("via1", tap_x - 0.075, y - 0.075, tap_x + 0.075, y + 0.075)
    box.call("metal2", tap_x - 0.20, y - 0.20, tap_x + 0.20, y + 0.20)
    box.call("via2", tap_x - 0.10, y - 0.10, tap_x + 0.10, y + 0.10)
    box.call("metal3", tap_x - 0.20, y - 0.30, tap_x + 0.20, y + 0.30)
    box.call("via3", tap_x - 0.10, y - 0.10, tap_x + 0.10, y + 0.10)
    box.call("metal4", [strap_x, tap_x].min - half, y - half, [strap_x, tap_x].max + half, y + half)
  end
end

# Join selector VGND from M4 directly to the grounded M3 top-dummy bus.
ground_y = power.fetch("vgnd_guard_join_y_absolute_um")
box.call("metal3", vgnd_x - 0.31, ground_y - 0.20, vgnd_x + 0.31, ground_y + 0.20)
box.call("via3", vgnd_x - 0.10, ground_y - 0.10, vgnd_x + 0.10, ground_y + 0.10)
box.call("metal4", vgnd_x - 0.20, ground_y - 0.30, vgnd_x + 0.20, ground_y + 0.30)

# Promote every external macro interface label into the integration top at the
# already-existing access geometry.  This changes hierarchy/naming only; it
# deliberately adds no signal conductor and therefore cannot perturb the
# closed phase paths.
manifest.fetch("top_level_ports").each do |port|
  at = port.fetch("at_um")
  top.shapes(layers.fetch(port.fetch("layer"))).insert(
    Text.new(port.fetch("name"), Trans.new((at[0] / dbu).round, (at[1] / dbu).round)),
  )
end

layout.write(output_gds)
puts output_gds
