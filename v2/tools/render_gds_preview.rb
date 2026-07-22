# Render exact GDS geometry in a hidden KLayout view.
# Usage:
#   klayout -z -r render_gds_preview.rb -rd input=... -rd output=... \
#     -rd width=1600 -rd height=1200 -rd lyp=optional.lyp

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
view.zoom_fit
view.save_image($output, width, height)
puts "rendered #{$input} -> #{$output}"
