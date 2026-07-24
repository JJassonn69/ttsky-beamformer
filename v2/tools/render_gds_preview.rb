# Render exact GDS geometry in a hidden KLayout view.
# Usage:
#   klayout -z -r render_gds_preview.rb -rd input=... -rd output=... \
#     -rd width=1600 -rd height=1200 -rd lyp=optional.lyp \
#     -rd box=optional_x1,y1,x2,y2

raise "missing -rd input=..." unless defined?($input)
raise "missing -rd output=..." unless defined?($output)

width = defined?($width) ? $width.to_i : 1600
height = defined?($height) ? $height.to_i : 1200

main_window = RBA::Application.instance.main_window
main_window.create_layout(0)
# KLayout 0.30 returns the newly created CellView, while image/render methods
# live on the containing LayoutView.  Re-acquire that view explicitly so this
# script works on both the production Mac install and older Linux builds.
view = main_window.current_view
raise "KLayout did not create a layout view" if view.nil?
cell_view_index = view.load_layout($input)
cell_view = view.cellview(cell_view_index)
top = cell_view.layout.top_cell
raise "loaded GDS has no unique top cell" if top.nil?
cell_view.cell = top
view.load_layer_props($lyp) if defined?($lyp) && !$lyp.empty?
view.add_missing_layers
view.max_hier
if defined?($box) && !$box.empty?
  coordinates = $box.split(",").map(&:to_f)
  raise "-rd box requires x1,y1,x2,y2" unless coordinates.length == 4
  raise "-rd box must have positive width and height" unless (
    coordinates[2] > coordinates[0] && coordinates[3] > coordinates[1]
  )
  view.zoom_box(RBA::DBox.new(*coordinates))
else
  view.zoom_fit
end
view.save_image($output, width, height)
puts "rendered #{$input} -> #{$output}"
