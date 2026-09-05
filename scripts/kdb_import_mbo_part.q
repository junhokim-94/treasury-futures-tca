/ args: <csv_path> <out_dir>
if[2 > count .z.x; '"usage: q kdb_import_mbo_part.q <csv_path> <out_dir>"];

csvPath: first .z.x;
outDir: .z.x 1;
rows: 1_ read0 csvPath;

if[0 = count rows;
  t: ([] ts_ns:`long$(); instrument_id:`long$(); action:`symbol$(); order_id:`long$(); side:`symbol$(); price_ticks:`long$(); size:`long$());
  system "mkdir ", outDir;
  (`$outDir) set t;
  \\
];

cells: "," vs' rows;
t: ([] 
  ts_ns: "J"$ cells[; 0];
  instrument_id: "J"$ cells[; 1];
  action: `$ cells[; 2];
  order_id: "J"$ cells[; 3];
  side: `$ cells[; 4];
  price_ticks: "J"$ cells[; 5];
  size: "J"$ cells[; 6]
);

system "mkdir ", outDir;
(`$outDir) set t;
\\

