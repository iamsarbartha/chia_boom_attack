from functools import cached_property

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import Client, types
from google.adk.tools import agent_tool
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.tools import url_context



class GlobalGemini(Gemini):
  """Pins the Vertex AI client to the `global` location.

  gemini-3 series models are only served from `global`; the default ADK
  `Gemini` integration constructs a `google.genai.Client` whose location
  defaults to the AgentEngine instance's region (e.g. `us-central1`) and
  fails with model-not-found for these models. Subclassing per the override
  pattern documented on `google.adk.models.google_llm.Gemini` lets the agent
  keep running in its regional AgentEngine instance while routing the model
  request to the global endpoint.
  """

  @cached_property
  def api_client(self) -> Client:
        return Client(
            vertexai=True,
            location="global",
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(
                    attempts=10, initial_delay=5, max_delay=60, jitter=1
                )
            ),
        )


vulnerability_research_agent_google_search_agent = LlmAgent(
  name='Vulnerability_research_agent_google_search_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Agent specialized in performing Google searches.'
  ),
  sub_agents=[],
  instruction='Use the GoogleSearchTool to find information on the web.',
  tools=[
    GoogleSearchTool()
  ],
)
vulnerability_research_agent_url_context_agent = LlmAgent(
  name='Vulnerability_research_agent_url_context_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Agent specialized in fetching content from URLs.'
  ),
  sub_agents=[],
  instruction='Use the UrlContextTool to retrieve content from provided URLs.',
  tools=[
    url_context
  ],
)
vulnerability_research_agent_2 = LlmAgent(
  name='vulnerability_research_agent_2',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Look into original research papers, find relevant cache side-channels and define an attack flow.'
  ),
  sub_agents=[],
  instruction='Explore literature to find relevant cache side-channels for the different cache levels in RiscV boom given the specification.\n\nRead original papers, official advisories, and available reproductions.\nIdentify the mechanism, affected implementations, attacker capabilities,\nvictim behavior, security boundary, required hardware features, and expected observations.\n\nFormulate a frozen hypothesis and define explicit, measurable success criteria for the reproduction attempt before implementation.\n\nReturn a cited vulnerability specification, the frozen hypothesis, success criteria, and unresolved questions.\nAdditionally return why this vulnerability is applicable to Boom processor - and a planning flow on how it can be implemented.Finally return a report describing the above details.',
  tools=[
    agent_tool.AgentTool(agent=vulnerability_research_agent_google_search_agent),
    agent_tool.AgentTool(agent=vulnerability_research_agent_url_context_agent)
  ],
)
vulnerability_generator_google_search_agent = LlmAgent(
  name='Vulnerability_Generator_google_search_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Agent specialized in performing Google searches.'
  ),
  sub_agents=[],
  instruction='Use the GoogleSearchTool to find information on the web.',
  tools=[
    GoogleSearchTool()
  ],
)
vulnerability_generator_url_context_agent = LlmAgent(
  name='Vulnerability_Generator_url_context_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Agent specialized in fetching content from URLs.'
  ),
  sub_agents=[],
  instruction='Use the UrlContextTool to retrieve content from provided URLs.',
  tools=[
    url_context
  ],
)
vulnerability_generator = LlmAgent(
  name='vulnerability_generator',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'You create reproducible experiments for the approved hypothesis from the vulnerability research subagent.'
  ),
  sub_agents=[],
  instruction='Generate the victim and attacker C/assembly programs, build inputs, measurement procedure, and run manifest for the specified environment.\n\nInclude a matched negative control and a positive control that checks whether the measurement setup can detect the intended cache effect. Specify initialization, address placement, timer use, synchronization, trial count, seeds, and termination conditions.\n\nEnsure attacker inference uses only observations permitted by the threat model. Keep privileged debug instrumentation separate from attacker-visible measurements.\n\nSeparate calibration trials from held-out evaluation trials. Define success criteria before inspecting evaluation results.\n\nReceive validation feedback, logs, and failure details from the **Validator**. Iteratively modify and refine the code and experiment implementation based on the validator\'s output until the simulation results match the target outcome from the **Vulnerability research agent**. Record each revision and its purpose.\n\nReturn source files, exact build/run instructions, controls, and expected outcomes for both confirmation and falsification.\n\nUse Verilator simulator and Riscv build to run and validate the experiments. Fix build and other errors.',
  tools=[
    agent_tool.AgentTool(agent=vulnerability_generator_google_search_agent),
    agent_tool.AgentTool(agent=vulnerability_generator_url_context_agent)
  ],
)
validator_google_search_agent = LlmAgent(
  name='Validator_google_search_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Agent specialized in performing Google searches.'
  ),
  sub_agents=[],
  instruction='Use the GoogleSearchTool to find information on the web.',
  tools=[
    GoogleSearchTool()
  ],
)
validator_url_context_agent = LlmAgent(
  name='Validator_url_context_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Agent specialized in fetching content from URLs.'
  ),
  sub_agents=[],
  instruction='Use the UrlContextTool to retrieve content from provided URLs.',
  tools=[
    url_context
  ],
)
validator = LlmAgent(
  name='validator',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'This subagent validates the code generated by the vulnerability generator.\nAdditionally, it performs correlation with the vulnerability research agent result.'
  ),
  sub_agents=[],
  instruction='You execute approved experiments through build and simulation tools.\n\nVerify the experiment manifest and target revision. Build the required BOOM simulator and test binaries, then invoke VerilatorRunNode using the specified configuration, seeds, and limits.\n\nRecord commands, tool versions, exit codes, binary hashes, logs, measurement outputs, and requested waveforms. Reuse build artifacts only when their relevant source and configuration inputs match.\n\nRun the specified controls and experimental trials. Stop runs that exceed a 20 min time limit.\n\nCompare measurement outputs against the target outcome defined by the **Vulnerability research agent**, and provide detailed output and error logs back to the **Vulnerability Generator** so it can iterate on the code. Return additional instructions for the next iteration, including any evidence gaps or failure details.\n\nIf the validation is successful, provide a summary of the results and any remaining limitations or uncertainties.',
  tools=[
    agent_tool.AgentTool(agent=validator_google_search_agent),
    agent_tool.AgentTool(agent=validator_url_context_agent)
  ],
)
boom_cache_vulnerability_agent_google_search_agent = LlmAgent(
  name='Boom_cache_vulnerability_agent_google_search_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Agent specialized in performing Google searches.'
  ),
  sub_agents=[],
  instruction='Use the GoogleSearchTool to find information on the web.',
  tools=[
    GoogleSearchTool()
  ],
)
boom_cache_vulnerability_agent_url_context_agent = LlmAgent(
  name='Boom_cache_vulnerability_agent_url_context_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'Agent specialized in fetching content from URLs.'
  ),
  sub_agents=[],
  instruction='Use the UrlContextTool to retrieve content from provided URLs.',
  tools=[
    url_context
  ],
)
root_agent = LlmAgent(
  name='Boom_cache_vulnerability_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description=(
      'You coordinate the BOOM vulnerability exploration workflow.'
  ),
  sub_agents=[],
  instruction=(
      'You coordinate the BOOM vulnerability exploration workflow. Keep control '
      'of the conversation: call the research, generator, and validator agents '
      'as tools, read each response, and make the next delegation yourself. '
      'Do not transfer the conversation to a worker.\n\n'
      'Start by recording the BOOM and Chipyard commits, configuration, '
      'Verilator version, cache parameters, memory model, and resource budget. '
      'Assign one published vulnerability mechanism to each experiment and '
      'maintain a shared experiment record.\n\n'
      '1. Call vulnerability_research_agent_2 with the cache report. Wait for '
      'its cited vulnerability specification, frozen hypothesis, and success '
      'criteria.\n'
      '2. Call vulnerability_generator with the research result and hardware '
      'constraints. Wait for its source files, controls, and run manifest.\n'
      '3. Call validator with the frozen criteria and generator output. Wait '
      'for its build, simulation, and correlation results.\n'
      '4. When validation requests revisions, call vulnerability_generator '
      'again with the validator feedback, then call validator with the revised '
      'experiment. Pass the relevant worker output into each subsequent call.\n\n'
      'Compare validation results with the frozen research criteria. For an '
      'implementation error, send logs and failure details to the generator. '
      'For a valid but inconclusive result, send the evidence gap to the '
      'generator. For a valid negative result, record falsification and stop '
      'or try a pre-approved revision. When criteria are met, conduct an '
      'independent review and report as reproduced.\n\n'
      'Allow at most three build-repair attempts and three experiment revisions '
      'unless the user sets another budget. Enforce simulation timeouts and '
      'preserve all attempt records. Invoke mitigation only after the '
      'independent reviewer accepts a reproduced finding, and preserve the '
      'original reproduction artifacts.\n\n'
      'After the workers return, produce your own final response with one '
      'status: not_applicable, inconclusive, reproduced, or '
      'mitigation_evaluated. Summarize the trajectory, evidence, and '
      'outstanding limitations in the final report.'
  ),
  tools=[
    agent_tool.AgentTool(agent=vulnerability_research_agent_2),
    agent_tool.AgentTool(agent=vulnerability_generator),
    agent_tool.AgentTool(agent=validator),
    agent_tool.AgentTool(agent=boom_cache_vulnerability_agent_google_search_agent),
    agent_tool.AgentTool(agent=boom_cache_vulnerability_agent_url_context_agent)
  ],
)