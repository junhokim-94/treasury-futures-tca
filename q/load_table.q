if[3>count .z.x; '"usage: q load_table.q <hdb_root> <table_name> <csv_path>"];

hdbRoot:first .z.x;
tableName:.z.x 1;
csvPath:.z.x 2;

\l q/schema.q

dbHandle:hsym first `$enlist hdbRoot;
csvHandle:hsym first `$enlist csvPath;

rows:1_ read0 csvHandle;
t:$[tableName~"mbo_event"; parseMboEventCsv rows; tableName~"instrument_def"; parseInstrumentDefCsv rows; '"unknown_table"];
rowsCount:count t;

if[0=rowsCount; \\];

tblSym:first `$enlist tableName;
parts:asc distinct t`date;
if[1<count parts; '"multi_date_csv_not_supported"];
part:first parts;
tblSym set t where (t`date)=part;
.Q.dpft[dbHandle; part; `instrument_id; tblSym];
\\

