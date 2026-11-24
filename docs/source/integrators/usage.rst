Runtime API reference
=====================

Installation
------------

Install IvoryOS with pip:

.. code-block:: console

   pip install ivoryos

Launch IvoryOS
--------------

.. code-block:: python

   import ivoryos

   ivoryos.run(__name__)

.. autofunction:: ivoryos.run


Choose which objects become instruments
---------------------------------------

At startup IvoryOS looks at every module-level object in your script and lists each one it parses as an instrument. It skips objects that are not instruments:

- plain values, imported modules, classes and functions
- names that start with ``_`` or a capital letter
- objects whose class comes from the Python standard library, such as a ``Path``, ``Lock``, ``Queue`` or ``Logger``
- data, plotting and web objects, such as a pandas ``DataFrame``, a numpy array, a matplotlib figure or a Flask app
- objects with no public method or property

Objects from your own code and from instrument driver packages, such as ``pyserial`` or ``pyvisa``, are parsed. The console lists what was skipped and why.

To hide an object, or to parse one that was skipped:

.. code-block:: python

   import pandas as pd

   calibration = pd.DataFrame(...)  # skipped: a pandas DataFrame
   OT2 = OpentronsDriver(...)       # skipped: the name starts with a capital letter
   camera = Camera(...)             # parsed, but you want it hidden

   ivoryos.run(__name__, exclude_names=["camera"], include_names=["OT2"])

A name in both lists stays hidden.


Add loggers
-----------

To add one or more loggers:

.. code-block:: python

   ivoryos.run(__name__, logger="logger name")
   ivoryos.run(__name__, logger=["logger 1", "logger 2"])

By default, logs are saved to ``default.log``. You can choose another log file name:

.. code-block:: python

   from datetime import datetime

   ivoryos.run(
       __name__,
       logger_output_name=f"log_{datetime.today().strftime('%Y-%m-%d')}.log",
   )


Add notification handlers
-------------------------

Notification handlers can send messages, such as email, SMS, or Slack notifications, when a workflow uses ``Pause``.

.. code-block:: python

   def slack_bot(message: str):
       # Send message to a Slack channel.
       pass


   ivoryos.run(__name__, notification_handler=slack_bot)
   ivoryos.run(__name__, notification_handler=[slack_bot, another_notification_handler])


Parameter type conversion
-------------------------

For the integrator-facing guide to typed UI controls, including Enum dropdowns, see :doc:`input-types`.

The parameter converter supports the following basic types:

``int``, ``float``, ``str``, ``bool``, ``list``, ``tuple``, ``set``

When defining functions for scripting workflows, use these supported types as type hints to enable automatic parameter conversion.

If a parameter type hint is not one of the supported types, IvoryOS attempts to evaluate it with ``ast.literal_eval()``. If evaluation fails, the parameter is treated as ``str``.

.. code-block:: python

   def example_function(param1: int, param2: float, param3: str, param4: bool, param5: list):
       """
       When calling example_function from the workflow interface:
       param1 will be converted to int
       param2 will be converted to float
       param3 will remain str
       param4 will be converted to bool
       param5 will be converted to list
       """
       pass


   ivoryos.run(__name__)


Design agent
------------

The design agent simplifies workflow creation by allowing users to generate experimental actions with natural language. Instead of manually searching through available methods, you can describe your intent, and the agent extracts likely actions from all instruments in the current deck configuration. It also supports the flow-control functions ``wait`` and ``comment``.

.. raw:: html

   <iframe width="495" height="315" src="https://www.youtube.com/embed/MopfBnEOlK0?autoplay=1&mute=1&loop=1&playlist=MopfBnEOlK0&controls=0" frameborder="0" allow="autoplay; encrypted-media" allowfullscreen></iframe>

*Natural language input with the* ``abstract_sdl`` *deck, using the* ``qwen3-30b-a3b-instruct-2507`` *model.*

Configuration
~~~~~~~~~~~~~

The design agent supports any large language model compatible with the OpenAI Chat Completions API v1. If ``OPENAI_API_KEY``, ``model``, or ``llm_server`` is missing or incorrect, IvoryOS starts without the design-agent feature.

Set the API key as an environment variable or create a ``.env`` file in the project root:

.. code-block:: text

   OPENAI_API_KEY=<your_key_here>

Pass the ``model`` name and ``llm_server`` base URL to ``ivoryos.run(...)``.

Cloud LLM provider
~~~~~~~~~~~~~~~~~~

Use this configuration to connect to remote providers.

.. code-block:: python

   import ivoryos

   if __name__ == "__main__":
       ivoryos.run(__name__, model="gpt-4o", llm_server="https://api.openai.com/v1")

Local LLM provider
~~~~~~~~~~~~~~~~~~

The OpenAI-compatible API implementation also allows locally hosted LLMs.

.. code-block:: python

   import ivoryos

   if __name__ == "__main__":
       ivoryos.run(__name__, model="qwen3-30b-a3b-instruct-2507", llm_server="http://localhost:11434/v1/")

.. note::

   For every request, the agent saves the full prompt and raw JSON response to ``ivoryos_data/llm_output/`` for debugging and transparency.

Tips for model selection and daily use
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Minimum model requirement**: for consistent JSON output, a model equivalent to ``meta-llama-3.1-8b-instruct`` or better is recommended.
- **Model size**: modern models and models with more than 8B parameters are usually more reliable but require more compute.
- **Avoid thinking models**: reasoning models are not recommended because of increased output time.
- **Improve with documentation**: rigorous method and class documentation improves accuracy because extracted docs are used as LLM context.
- **Prompt clarity**: shorter and more direct user prompts tend to be more reliable.
