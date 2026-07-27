# Merge the exact channel and root-aligned selector, then draw the eight
# straight M2/via2/M3/via3/M4 joins described by channel_selector_join.json.
require "json"
include RBA

root = File.expand_path(ENV.fetch("V3_PROJECT_ROOT"))
channel_gds = File.expand_path(ENV.fetch("V3_CHANNEL_GDS"))
selector_gds = File.expand_path(ENV.fetch("V3_SELECTOR_GDS"))
output_gds = File.expand_path(ENV.fetch("V3_JOINED_GDS"))
manifest = JSON.parse(File.read(File.join(root, "v3/layout/channel_selector_join.json")))

layout = Layout.new
layout.read(channel_gds)
layout.read(selector_gds)
channel = layout.cell("v3_channel_input_bias_pilot")
selector = layout.cell("v3_selector_route_pilot")
raise "channel top missing" if channel.nil?
raise "selector top missing" if selector.nil?
top = layout.create_cell("v3_channel_selector_pilot")
top.insert(CellInstArray.new(channel.cell_index, Trans.new))
selector_origin = manifest.fetch("selector_instance_origin_um")
top.insert(CellInstArray.new(selector.cell_index, Trans.new((selector_origin[0] / layout.dbu).round, (selector_origin[1] / layout.dbu).round)))

layers = {
  "metal2" => layout.layer(LayerInfo.new(69, 20)),
  "via2" => layout.layer(LayerInfo.new(69, 44)),
  "metal3" => layout.layer(LayerInfo.new(70, 20)),
  "via3" => layout.layer(LayerInfo.new(70, 44)),
  "metal4" => layout.layer(LayerInfo.new(71, 20)),
}
origin = manifest.fetch("channel_gds_origin_um")
dbu = layout.dbu
box = lambda do |layer_name, x1, y1, x2, y2|
  top.shapes(layers.fetch(layer_name)).insert(Box.new((x1 / dbu).round, (y1 / dbu).round, (x2 / dbu).round, (y2 / dbu).round))
end

manifest.fetch("joins").each do |join|
  x = origin[0] + join.fetch("x_um")
  selector_y = origin[1] + join.fetch("selector_pin_center_y_um")
  transition_y = origin[1] + join.fetch("transition_y_um")
  root_y = origin[1] + join.fetch("analog_root_y_um")
  # Direct vertical conductors.  The small overlap below the analog root
  # ensures a geometric union with the closed tree trunk after flattening.
  box.call("metal2", x - 0.15, transition_y, x + 0.15, selector_y)
  box.call("metal4", x - 0.15, root_y - 0.20, x + 0.15, transition_y)
  # One legal stacked transition.  M3 provides only the via landing; it does
  # not become a horizontal route or a dead-end stub.
  box.call("metal2", x - 0.20, transition_y - 0.20, x + 0.20, transition_y + 0.20)
  box.call("via2", x - 0.10, transition_y - 0.10, x + 0.10, transition_y + 0.10)
  box.call("metal3", x - 0.31, transition_y - 0.20, x + 0.31, transition_y + 0.20)
  box.call("via3", x - 0.10, transition_y - 0.10, x + 0.10, transition_y + 0.10)
  box.call("metal4", x - 0.20, transition_y - 0.20, x + 0.20, transition_y + 0.20)
end

layout.write(output_gds)
puts output_gds
