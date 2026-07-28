# KLayout-native structural probe for the exact packaged TinyTapeout GDS.

require "json"

layout = RBA::Layout.new
layout.read($input)
top_cells = layout.top_cells.map(&:name).sort
top = layout.cell($top_cell)
raise "missing top cell #{$top_cell}" if top.nil?

def box_array(box)
  [box.left, box.bottom, box.right, box.top]
end

boundary_index = layout.find_layer(235, 4)
raise "missing prBoundary 235/4" if boundary_index.nil?
boundary = RBA::Region.new(top.begin_shapes_rec(boundary_index))

layers = layout.layer_indices.map do |index|
  info = layout.get_info(index)
  [info.layer, info.datatype]
end.uniq.sort

report = {
  "schema_version" => 1,
  "top_cells" => top_cells,
  "selected_top" => top.name,
  "database_unit_um" => layout.dbu,
  "top_bbox_dbu" => box_array(top.bbox),
  "prboundary_bbox_dbu" => box_array(boundary.bbox),
  "prboundary_polygon_count_recursive" => boundary.count,
  "cell_names" => layout.each_cell.map(&:name).sort,
  "layer_pairs" => layers,
}

File.write($output, JSON.pretty_generate(report) + "\n")
