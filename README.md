[![Documentation Status](https://readthedocs.org/projects/ivoryos/badge/?version=latest)](https://ivoryos.readthedocs.io/en/latest/?badge=latest)
[![PyPI version](https://img.shields.io/pypi/v/ivoryos)](https://pypi.org/project/ivoryos/)
[![Downloads](https://pepy.tech/badge/ivoryos)](https://pepy.tech/project/ivoryos)
![License](https://img.shields.io/pypi/l/ivoryos)
[![YouTube](https://img.shields.io/badge/YouTube-tutorial-red?logo=youtube)](https://youtu.be/dFfJv9I2-1g)
[![YouTube](https://img.shields.io/badge/YouTube-demo-red?logo=youtube)](https://youtu.be/flr5ydiE96s)
[![Published](https://img.shields.io/badge/Nature_Comm.-paper-blue)](https://www.nature.com/articles/s41467-025-60514-w)
[![Community](https://img.shields.io/discord/1313641159356059770?label=Discord&logo=discord&color=5865F2)](https://discord.gg/3KdjhUmsYA)

<img src="https://gitlab.com/heingroup/ivoryos/raw/main/docs/source/_static/ivoryos_logo.png" alt="IvoryOS logo" width="100">

# [IvoryOS](https://ivoryos.ai): open-source orchestrator for self-driving labs

IvoryOS turns existing Python automation code into interactive controls, drag-and-drop workflows, and optimization-ready experiments.

Build for fast-changing R&D environments, and make Python-based lab automation accessible and scalable.

![code_launch_design.png](https://gitlab.com/heingroup/ivoryos/raw/main/docs/source/_static/code_to_ui.gif)

## Join our community!
IvoryOS is an open-source project under active development. We welcome feedback, feature ideas, and contributions 
from anyone working on or interested in self-driving laboratories.

Join our [Discord](https://discord.gg/3KdjhUmsYA) or [Slack](https://join.slack.com/t/ivoryos/shared_invite/zt-3mmwcu5f7-XIG42Ufyp~v450Fob0mj3A) to ask questions, share use cases, and help shape IvoryOS.

---

## Table of Contents

- [Installation](#installation)
- [System requirements](#system-requirements)
- [Features](#features)
- [Demo](#demo)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Acknowledgements](#acknowledgements)


## Installation
From PyPI:
```bash
pip install ivoryos
```

----
## System Requirements

**Platforms:** Compatible with Linux, macOS, and Windows (developed/tested on Windows).  
**Python:** Python ≥3.10  

<details>
<summary>Dependency groups</summary>

- Core: Flask, Flask-Login, Flask-Session, Flask-SocketIO, Flask-SQLAlchemy, Flask-WTF, WTForms, bcrypt, python-dotenv, pandas.
- Optimizers: `optimizer-ax`, `optimizer-baybe`, `optimizer-nimo`, or `optimizers` for all supported optimizer adapters.
- Database: `db` for PostgreSQL support.
- LLM design agent: `llm` for the optional in-app text-to-workflow feature.
- Development: `dev` for running the test suite.
</details>


<details>
<summary>Optional feature installs</summary>

```bash
pip install "ivoryos[optimizers]"       # all optimizer adapters
pip install "ivoryos[optimizer-ax]"     # Ax only
pip install "ivoryos[optimizer-baybe]"  # BayBE only
pip install "ivoryos[optimizer-nimo]"   # NIMO only
pip install "ivoryos[db]"               # PostgreSQL support
pip install "ivoryos[llm]"              # optional text-to-workflow design agent
```

From a local source checkout:
```bash
pip install -e ".[dev]"
pytest
```
</details>

<details>
<summary>32-bit Windows installation notes</summary>

Prefer 64-bit Python when possible. If you must deploy IvoryOS on 32-bit Windows, `pip` may not find pre-built 32-bit wheels for modern packages such as `greenlet`, `pandas`, or newer `Flask-Session` releases.

```bash
# 1. Use a Flask-Session release before the msgspec dependency.
pip install "Flask-Session<0.7"

# 2. Install a pandas wheel compatible with the local 32-bit Python environment.
pip install pandas --user --only-binary=:all:

# 3. Install greenlet from conda-forge if PyPI has no compatible wheel.
conda install -c conda-forge greenlet -y

# 4. Install IvoryOS.
pip install ivoryos
```

</details>


## Quick start
In your script, where you initialize or import your robot:
```python
my_robot = Robot()

import ivoryos

ivoryos.run(__name__)
```
Then run the script and visit `http://localhost:8000` in your browser.
Use `admin` for both username and password, and start building workflows!

----
## Features
### Direct control: 
direct function calling _Instruments_ tab
### Workflows
  - **Design Editor**: drag/add function to canvas in _Workflow_ tab, use `#parameter_name` for dynamic parameters, click `Prepare Run` button to go to the execution configuration page
  - **Execution Config**: configure iteration methods and parameters in _Execution_ tab. 
  - **Design Library**: manage workflow scripts in _Library_ tab.
  - **Workflow Data**: Execution records are in _Data_ tab.

<details>
<summary>Logging</summary>

Add single or multiple loggers:
```python
ivoryos.run(__name__, logger="logger name")
ivoryos.run(__name__, logger=["logger 1", "logger 2"])
```

</details>

<details>
<summary>Human-in-the-loop</summary>

Use `pause` in flow control to pause the workflow and send a notification with custom message handler(s). 
When run into `pause`, it will pause, send a message, and wait for human's response. Example of a Slack bot:
```python

def slack_bot(msg: str = "Hi"):
    """
    a function that can be used as a notification handler function("msg")
    :param msg: message to send
    """
    from slack_sdk import WebClient

    slack_token = "your slack token"
    client = WebClient(token=slack_token)

    my_user_id = "your user id"  # replace with your actual Slack user ID

    client.chat_postMessage(channel=my_user_id, text=msg)

import ivoryos
ivoryos.run(__name__, notification_handler=slack_bot)
```
Use `Input` in flow control to get human input during workflow execution. Example:

</details>

<details>
<summary>click to see the data folder structure</summary>

- **`ivoryos_data/`**: 
  - **`config_csv/`**: Batch configuration `csv`
  - **`pseudo_deck/`**: Offline deck `.pkl`
  - **`results/`**: Execution results
  - **`scripts/`**: Compiled workflows Python scripts
  - **`default.log`**: Application logs
  - **`ivoryos.db`**: Local database
</details>

---

## Demo
Online demo at [demo.ivoryos.ai](https://demo.ivoryos.ai). 
Local version in [abstract_sdl.py](https://gitlab.com/heingroup/ivoryos/-/blob/main/community/examples/abstract_sdl_example/abstract_sdl.py)

Videos:
- [Getting started with IvoryOS](https://youtu.be/iwRtIBsNFZ4): a narrated walkthrough, from your lab's Python to running a workflow and reading the results

---

## Roadmap
Check out our [Work Items](https://gitlab.com/heingroup/ivoryos/issues) for upcoming features and improvements.
- [ ] Support dataclass input
- [ ] Introspection version control
- [ ] Check config file compatibility

---


## Contributing

We welcome all contributions — from core improvements to new drivers, plugins, and real-world use cases.
See `CONTRIBUTING.md` for details.

---

## Citing

<details>
<summary>Click to see citations</summary>

If you find this project useful, please consider citing the following manuscript:

> Zhang, W., Hao, L., Lai, V. et al. [IvoryOS: an interoperable web interface for orchestrating Python-based self-driving laboratories.](https://www.nature.com/articles/s41467-025-60514-w) Nat Commun 16, 5182 (2025).

```bibtex
@article{zhang_et_al_2025,
  author       = {Wenyu Zhang and Lucy Hao and Veronica Lai and Ryan Corkery and Jacob Jessiman and Jiayu Zhang and Junliang Liu and Yusuke Sato and Maria Politi and Matthew E. Reish and Rebekah Greenwood and Noah Depner and Jiyoon Min and Rama El-khawaldeh and Paloma Prieto and Ekaterina Trushina and Jason E. Hein},
  title        = {{IvoryOS}: an interoperable web interface for orchestrating {Python-based} self-driving laboratories},
  journal      = {Nature Communications},
  year         = {2025},
  volume       = {16},
  number       = {1},
  pages        = {5182},
  doi          = {10.1038/s41467-025-60514-w},
  url          = {https://doi.org/10.1038/s41467-025-60514-w}
}
```

For an additional perspective related to the development of the tool, please see:

> Zhang, W., Hein, J. [Behind IvoryOS: Empowering Scientists to Harness Self-Driving Labs for Accelerated Discovery](https://communities.springernature.com/posts/behind-ivoryos-empowering-scientists-to-harness-self-driving-labs-for-accelerated-discovery). Springer Nature Research Communities (2025).

```bibtex
@misc{zhang_hein_2025,
  author       = {Wenyu Zhang and Jason Hein},
  title        = {Behind {IvoryOS}: Empowering Scientists to Harness Self-Driving Labs for Accelerated Discovery},
  howpublished = {Springer Nature Research Communities},
  year         = {2025},
  month        = {Jun},
  day          = {18},
  url          = {https://communities.springernature.com/posts/behind-ivoryos-empowering-scientists-to-harness-self-driving-labs-for-accelerated-discovery}
}
```
</details>

---
## Acknowledgements
Authors acknowledge Telescope Innovations Corp., UBC Hein Lab, and Acceleration Consortium members for their valuable suggestions and contributions.
