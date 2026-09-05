if[1>count .z.x; '"usage: q init_hdb.q <hdb_root>"];
hdbRoot:first .z.x;
@[system; "mkdir \"", hdbRoot, "\""; {[]}];
\\

