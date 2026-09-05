# L3 replay dashboard

Run commands from the repository root with the project environment active.

```powershell
python -m pip install -e ".[data,dashboard]"
python scripts/run_l3_dashboard.py --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/ in a browser. Enter your local MBO and Definition
DBN paths, select the instrument, and start replay. Relative paths resolve
from the server working directory. The example files `data/session.mbo.dbn.zst`
and `data/session.definition.dbn.zst` are not included.

The dashboard shows reconstructed depth, order queues, and simulated execution
statistics over `/ws/replay`. Keep the default loopback binding: the research
server accepts local file paths and has no authentication. Stop with Ctrl+C.

