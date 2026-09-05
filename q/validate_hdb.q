if[2>count .z.x; '"usage: q validate_hdb.q <hdb_root> <out_json_path>"];

hdbRoot:first .z.x;
outJsonPath:.z.x 1;
\l q/schema.q
system "l ",hdbRoot;

mboExists:`mbo_event in tables[];
defExists:`instrument_def in tables[];

mboRows:$[mboExists; count mbo_event; 0j];
defRows:$[defExists; count instrument_def; 0j];

mboCols:$[mboExists; cols mbo_event; `symbol$()];
defCols:$[defExists; cols instrument_def; `symbol$()];

mboParts:`date$();
defParts:`date$();

mboInvalidActionCount:$[mboExists; count select from mbo_event where not action in `ADD`CANCEL`MODIFY`TRADE`FILL`DELETE`RESET; 0j];
mboInvalidSideCount:$[mboExists; count select from mbo_event where not side in `B`A`; 0j];
mboNullEventDateCount:$[mboExists; count select from mbo_event where null event_date; 0j];
defNullInstrumentCount:$[defExists; count select from instrument_def where null instrument_id; 0j];
defEmptyRawSymbolCount:$[defExists; count select from instrument_def where null raw_symbol; 0j];

mboStats:(`exists`rows`cols`missing_cols`partitions`invalid_action_count`invalid_side_count`null_event_date_count)!(mboExists;mboRows;mboCols;mboEventCols except mboCols;mboParts;mboInvalidActionCount;mboInvalidSideCount;mboNullEventDateCount);
defStats:(`exists`rows`cols`missing_cols`partitions`null_instrument_id_count`empty_raw_symbol_count)!(defExists;defRows;defCols;instrumentDefCols except defCols;defParts;defNullInstrumentCount;defEmptyRawSymbolCount);

out:(`mbo_event`instrument_def)!(mboStats;defStats);
outHandle:hsym first `$enlist outJsonPath;
outHandle 0: enlist .j.j out;
\\

