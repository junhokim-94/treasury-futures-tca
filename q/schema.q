/ Shared schemas and CSV parsers for parquet->kdb load.

mboEventCols:`date`event_date`ts_event_ns`ts_recv_ns`instrument_id`raw_symbol`action`side`order_id`price_ticks`size`flags`sequence;
instrumentDefCols:`date`instrument_id`raw_symbol`min_price_increment`price_scale`multiplier`asset_class`exchange`expiry;
ingestLogCols:`load_ts`table_name`source_file`row_count`min_date`max_date`status;

schemaMboEvent:{
  ([] 
    date:`date$();
    event_date:`date$();
    ts_event_ns:`long$();
    ts_recv_ns:`long$();
    instrument_id:`long$();
    raw_symbol:`symbol$();
    action:`symbol$();
    side:`symbol$();
    order_id:`long$();
    price_ticks:`long$();
    size:`long$();
    flags:`long$();
    sequence:`long$()
  )
 };

schemaInstrumentDef:{
  ([] 
    date:`date$();
    instrument_id:`long$();
    raw_symbol:`symbol$();
    min_price_increment:`float$();
    price_scale:`long$();
    multiplier:`float$();
    asset_class:`symbol$();
    exchange:`symbol$();
    expiry:`date$()
  )
 };

schemaIngestLog:{
  ([] 
    load_ts:`timestamp$();
    table_name:`symbol$();
    source_file:`symbol$();
    row_count:`long$();
    min_date:`date$();
    max_date:`date$();
    status:`symbol$()
  )
 };

parseMboEventCsv:{[rows]
  if[0=count rows; :schemaMboEvent[]];
  cells: "," vs' rows;
  ([] 
    date:"D"$cells[;0];
    event_date:"D"$cells[;1];
    ts_event_ns:"J"$cells[;2];
    ts_recv_ns:"J"$cells[;3];
    instrument_id:"J"$cells[;4];
    raw_symbol:`$cells[;5];
    action:`$cells[;6];
    side:`$cells[;7];
    order_id:"J"$cells[;8];
    price_ticks:"J"$cells[;9];
    size:"J"$cells[;10];
    flags:"J"$cells[;11];
    sequence:"J"$cells[;12]
  )
 };

parseInstrumentDefCsv:{[rows]
  if[0=count rows; :schemaInstrumentDef[]];
  cells: "," vs' rows;
  ([] 
    date:"D"$cells[;0];
    instrument_id:"J"$cells[;1];
    raw_symbol:`$cells[;2];
    min_price_increment:"F"$cells[;3];
    price_scale:"J"$cells[;4];
    multiplier:"F"$cells[;5];
    asset_class:`$cells[;6];
    exchange:`$cells[;7];
    expiry:"D"$cells[;8]
  )
 };

