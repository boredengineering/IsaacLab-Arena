title: "Recursive self-improvement of AI research agents"
authors:

* Dhruv Srikanth (Weco AI)

* Bingchen Zhao (Weco AI)

* Dixing Xu (Weco AI)

* Yuxiang Wu (Weco AI)

* Zhengyao Jiang (Weco AI)
  date: 2026-09-23
  arxiv: 2609.26457v1 \[cs.AI\]
  correspondence: "dhruv@weco.ai, zhengyao@weco.ai"

# Recursive self-improvement of AI research agents

**Dhruv Srikanth**$$^1$$, **Bingchen Zhao**$$^1$$, **Dixing Xu**$$^1$$, **Yuxiang Wu**$$^1$$, and **Zhengyao Jiang**$$^1$$

$$^1$$*Weco AI*

*Correspondence:* `dhruv@weco.ai`, `zhengyao@weco.ai`

*arXiv:2609.26457v1 \[cs.AI\] 22 Sep 2026*

### Abstract

AI agents are beginning to automate research and development across the AI stack, from improving training efficiency to optimizing inference. A natural next step is to improve the research efficiency of the agents themselves. When an AI research agent's own code is the object of optimization, each accepted rewrite becomes the agent that the next round edits. We refer to this loop as **recursive self-improvement**. Its significance lies in a long-standing trend, in which increased cumulative spending on R&D yields diminishing returns. Sustained self-improvement offers a way to counter this trend. We present $$\text{AIDE}^2$$, a system that implements this loop for a frontier AI research agent. It proposes changes to its own code, benchmarks modified versions of itself on a suite of AI R&D tasks, and keeps the changes that perform best on hidden evaluations. In an autonomous 8-day run, $$\text{AIDE}^2$$ discovered seven successive improvements, ranging from a new search policy to memory mechanisms that compress and manage the agent's growing context. These gains generalize to four held-out benchmarks spanning machine learning engineering, heuristic algorithm engineering, and physics-based weather forecasting, the last of which is out of distribution from the selection tasks. On all four, the strongest discovered agent matches or exceeds a human-engineered production research agent that ranks among the strongest on FML-Bench. On a separate held-out task family, the discovered agents also exhibit reduced reward hacking, a property the loop never explicitly optimized for: the rate falls from 55% to 32% during the run, 7 percentage points below the human-engineered agent. Together, these results show that an AI research agent can improve its own research efficiency through recursive self-improvement, and that these gains transfer to tasks and domains the loop never encountered.

## 1. Introduction

AI agents are now used extensively to accelerate and automate parts of research and development (R&D) across the AI stack, from machine learning engineering (Jiang et al., 2025; Toledo et al., 2025; Karpathy, 2026) and GPU kernel engineering (Novikov et al., 2025; Liao et al., 2026) to algorithmic discovery (Liu et al., 2024; Lange et al., 2026) and the design of agent pipelines and harnesses (Zhang et al., 2025; Agrawal et al., 2026b; Hu et al., 2025; Lee et al., 2026). Beyond individual components, agents now run complete research workflows, from generating research ideas (Si et al., 2025b; Baek et al., 2025) to executing experiments and writing papers (Schmidgall et al., 2025; Lu et al., 2026; Jansen et al., 2025). Such systems improve the efficiency of the artifacts they produce, such as training and inference efficiency, yet the efficiency of the research process producing them remains fixed. In conventional R&D, further progress requires increased human effort, making continued improvement increasingly costly as research becomes more difficult (Bloom et al., 2020).

Recursive self-improvement (RSI) points the research process at itself. The prospect of an AI system that improves itself more efficiently than human researchers has been discussed since the earliest days of computing (Good, 1965) and remains an active subject of debate (Yudkowsky, 2013; Weston and Foerster, 2025). Recent self-improving systems show promise in coding and other domains (Zelikman et al., 2024; Zhang et al., 2026a; Wang et al., 2026; Zhang et al., 2026b), yet the effectiveness of their improvement loops at optimizing frontier AI research efficiency remains unclear.

In this work, we study how recursive self-improvement can effectively advance frontier AI R&D. Our experiments target the **harness layer**, the code that surrounds a model and controls an agent's search, context, and verification. As shown in Appendix C, a substantial share of an agent's realized capability is determined here. We present $$\text{AIDE}^2$$, a two-loop system that carries out recursive self-improvement at the harness layer. In the inner loop, a research agent optimizes code against a measurable objective on problems drawn from a diverse set of AI R&D tasks. The outer loop performs a meta-level optimization over this inner-loop research process, rewriting the research agent with the objective of improving the research efficiency of the inner-loop agent. Figure 1 illustrates this two-loop process structured as a nested tree search.

In one autonomous 8-day run, $$\text{AIDE}^2$$ discovered seven successive improvements, each accepted only after it improved results on held-out data that the agent being rewritten never observes. We compare the discovered agents against $$\text{AIDE}_{\text{human}}$$, a production research agent developed over two years of human-driven R&D that ranks among the strongest on FML-Bench (Zou et al., 2026). The strongest discovered agent matches or exceeds this baseline on four external benchmarks that never influenced the run. On a separate held-out task family, the reward hacking rate falls from 55% to 32%, below the 39% of the human-engineered agent. When used as the outer-loop agent, a discovered agent continues to produce accepted improvements, though due to compounding noise across both loops and the prohibitive cost of running additional seeds, its performance in that role cannot be decisively distinguished from the strong baseline.

In summary, we present $$\text{AIDE}^2$$, a recursive self-improvement system in which an AI research agent improves its own research efficiency. Across the recursive self-improvement run, the loop repeatedly finds and accepts improvements under a fixed evaluation budget. Those improvements generalize beyond the tasks used to select them, carry over to a domain the loop never encountered, and come with a reduction in reward hacking that was not part of the objective being optimized for. Measured against a strong baseline developed over two years of human-driven R&D, the discovered agents match or outperform it on the held-out benchmarks.

## 2. Method

We frame recursive self-improvement as a bi-level optimization problem consisting of two loops that iteratively optimize an agent against a measurable outcome. The inner loop acts on specific tasks designed to capture an agent's ability to optimize code within a subset of AI R&D domains. The outer loop operates on a meta-level, working to improve the inner-loop agent's optimization capability. Each inner-loop agent is evaluated at a fixed budget; therefore, improving the optimization capability directly improves the research efficiency of the inner-loop agent. Each accepted rewrite becomes the agent that the next step edits and evaluates. Both loops are driven by agents of the same tree-search design. Figure 1 illustrates this bi-level optimization process.

### 2.1. Recursive self-improvement

#### The inner loop

Given a codebase and a measurable metric, an inner-loop agent, denoted $a$, iteratively edits the code to improve performance under that metric. We write $x$ for a candidate solution and $r_t^{\text{pub}}$ for the signal the agent observes on a task $t$. Let $x_0$ denote the task's existing codebase and $x_{<i}$ the edits produced so far. The agent repeatedly proposes candidates (eq. (1)) until a fixed dollar budget $b_t$ is spent, covering the agent's tokens and the cost of executing its solutions:

$$
x_i = a\left(x_{<i}, r_t^{\text{pub}}(x_{<i})\right) \tag{1}
$$

The agent then returns one solution of its own choosing, which we denote $\hat{x}_t$. Which candidate to edit next, which to return, and how to structure the agent's memory are all part of the agent's code and are editable by the outer loop.

#### Grading an agent

When evaluated, an agent receives a fixed set of tasks spanning three families of AI R&D work, which we refer to as the **selection benchmark** (detailed in Section 2.2). We construct the task set to be diverse in order to induce evolutionary pressure on the types of improvements that are made to the inner-loop agent, namely general mechanisms over task-specific tricks. Once the agent is run on each task, it returns a candidate solution to be scored on private held-out data using $r_t^{\text{priv}}$. The resulting private scores are then aggregated:

$$
g(a) = \frac{1}{T}\sum_{t=1}^T r_t^{\text{priv}}(\hat{x}_t), \tag{2}
$$

where $\hat{x}_t$ is the solution returned by the agent $a$ on task $t$ and $T$ is the number of tasks in the selection benchmark. In practice, each task is run several times independently and the scores are averaged across runs.

#### The outer loop

An agent is itself written in code. Therefore, the same procedure can be applied one level up. At step $k$, the outer-loop agent $a^{\text{out}}$ reads the previously proposed agents and their grades and proposes a rewrite. Under the substitution $(a, x, r_t^{\text{pub}}) \mapsto (a^{\text{out}}, a, g)$, we can rewrite eq. (1) as:

$$
a_k = a^{\text{out}}\left(a_{<k}, g(a_{<k})\right) \tag{3}
$$

In practice, the outer-loop agent edits the current incumbent, so each accepted rewrite becomes the codebase that is edited at the next step. At step $k$, the incumbent is the best agent graded so far. Candidate selection differs between the two levels: inner-loop selection is part of the agent's editable policy and is repeatedly rewritten during the run, whereas outer-loop selection is fixed by:

$$
a_k^* = \arg\max_{a \in a_{\le k}} g(a) \tag{4}
$$

Since the outer loop selects inner-loop agents according to $g$, two properties of $g$ shape the resulting selection pressure:

1. Separating the inner loop's optimization signal $r_t^{\text{pub}}$ from the outer loop's selection signal $g$ (driven by $r_t^{\text{priv}}$) prevents the inner-loop agent from directly optimizing the criterion used for outer-loop selection.

2. Evaluating all agents under the same per-task budget $b_t$ constrains improvements to arise from a better algorithm rather than from spending additional compute.

### Algorithm 1: Recursive self-improvement

```
Require: initial agent a_0, outer-loop agent a^out, tasks {t} with budgets {b_t}, trajectory length K

 1: function GRADE(a)
 2:    for all tasks t = 1, ..., T do                           ▷ run a on each task
 3:       x_0 ← task t's existing codebase; i ← 0
 4:       while total cost < b_t do                             ▷ agent tokens + solution execution
 5:          i ← i + 1
 6:          x_i ← a(x_{<i}, r_t^pub(x_{<i}))                   ▷ propose the next solution
 7:       end while
 8:       x^_t ← the solution a selects from x_{≤i}
 9:    end for
10:    return (1 / T) * \sum_{t=1}^T r_t^priv(x^_t)             ▷ private held-out grading
11: end function

12: g(a_0) ← GRADE(a_0)                                         ▷ establish baseline grade
13: for k = 1, ..., K - 1 do
14:    a_k ← a^out(a_{<k}, g(a_{<k}))                           ▷ propose an agent rewrite
15:    g(a_k) ← GRADE(a_k)
16: end for
17: return a_{K-1}^* = argmax_{a \in a_{<K}} g(a)

```

### 2.2. $\text{AIDE}^2$

We instantiate Algorithm 1 through our system $\text{AIDE}^2$. The inner-loop agent $a_0$ starts from $\text{AIDE}_0$, a pared-down refactor of AIDE (Jiang et al., 2025). AIDE was originally designed for ML engineering and performed well on MLE-Bench (Chan et al., 2025). However, due to the diversity of tasks we run RSI on, we require a more general-purpose optimization agent. To this end, we remove the ML-specific machinery but maintain the same tree-search procedure. $\text{AIDE}_0$ grows a tree of candidate solutions rooted in an existing codebase, optimizing against a prespecified metric. The agent consists of several operators designed for different purposes:

* **`draft`**: explores broad sets of new ideas.

* **`debug`**: repairs a solution with a bug or execution error.

* **`improve`**: refines a promising direction.

Which solution is operated on is determined by the agent's search policy. In $\text{AIDE}_0$, the selection is greedy: the highest-scoring solution becomes the parent for the next operation. $\text{AIDE}_0$ employs a reviewer agent that reads execution outputs from evaluating solutions and extracts a score and any relevant feedback.

The outer-loop agent $a^{\text{out}}$ is driven by $\text{AIDE}_{\text{human}}$, an autonomous research agent used in production and developed by Weco's R&D team. $\text{AIDE}_{\text{human}}$ largely follows the same design choices and agent architecture as $\text{AIDE}_0$. In addition to serving as the outer-loop agent, $\text{AIDE}_{\text{human}}$ is used as a strong baseline developed through human-driven R&D when testing generalization at various levels: on the selection benchmark (Section 3.2), on held-out tasks in and out of distribution (Section 3.3), and in the discovered agents' ability to act as a better self-improver (Section 3.6). In Appendix B, we show that $\text{AIDE}_{\text{human}}$ is competitive with existing code optimization agents, supporting its use as a strong baseline.

During the recursive self-improvement run, we hold the model fixed within each loop:

* Outer loop: **Claude Opus 4.7** (Anthropic, 2026b).

* Inner loop: **Gemini 3 Flash** (Google DeepMind, 2025).

At the task-specific budgets $b_t$, Gemini 3 Flash matched or slightly exceeded the more expensive models tested on the selection tasks, so we use it for all inner-loop evaluations. Because evaluating each candidate dominates the cost of proposing it, we use the more capable model to drive the outer-loop agent. For the same reason, the inner-loop reviewer makes a single LLM call over each solution's execution output, while the outer-loop agent's reviewer explores the evaluation artifacts over several steps.

The **selection benchmark** consists of three task families:

1. **ML engineering**: asks the agent to train a model against a target metric.

2. **Heuristic algorithm engineering**: covers competitive-programming-style combinatorial problems where progress comes from iterating on algorithms and heuristics.

3. **Harness engineering**: targets improvements to an agent's prompts, context management, and feedback loops—the code and algorithms that turn LLM API calls into working agentic systems.

Every inner-loop agent $a_k$ is run across the task families under a fixed budget and evaluated on a private held-out set. Its private scores are then aggregated to produce a grade $g(a_k)$, which $\text{AIDE}_{\text{human}}$ uses as the selection signal to drive subsequent improvements of the inner-loop agent.

## 3. Experiments

### 3.1. Experimental design

To better understand the effectiveness of recursive self-improvement on AI R&D tasks, we use the following criteria and constraints when designing our experiments:

* **Repeated improvements:** The same run must produce several new incumbents throughout the optimization, as one favorable rewrite cannot show that the loop repeatedly finds useful improvements.

* **Fixed compute/evaluation budget:** Every agent produced during the RSI run is evaluated under a fixed evaluation budget so that a measured gain reflects a better algorithm rather than additional compute.

* **Transfer beyond selection:** Improvements selected on a set of tasks must remain useful on tasks that were not involved in selection to rule out overfitting.

* **Comparison to strong baselines:** Discovered agents are benchmarked against $\text{AIDE}_{\text{human}}$.

### 3.2. A sustained trend of improvements

We ran $\text{AIDE}^2$ over 8 days of wall-clock time, producing a 100-node trajectory containing the initial agent and 99 rewrite proposals. Seven accepted improvements occurred at steps **2, 6, 28, 39, 47, 63, and 85**, with the incumbent grade rising from $0.703$ to $0.778$:

* **Step 2:** Bandit search over strategies

* **Step 6:** Demands a root-cause diagnosis before any fix

* **Step 28:** Escapes plateaus by forking its champion

* **Step 39:** Repairs itself after a crashed robustness fix attempt

* **Step 47:** Patches an error that crashed evaluations

* **Step 63:** Compresses log spam before reading it

* **Step 85:** Demotes a failure-prone draft strategy

Two further complete runs of the same protocol also produced sustained improvements, accepting two and four rewrites, respectively. The improved agents eventually outperformed $\text{AIDE}_{\text{human}}$ ($g = 0.749$) on the selection benchmark (first-order generalization).

### 3.3. Generalization to held-out benchmarks

We test **second-order generalization**: whether improvements remain useful on four external benchmarks that never affected candidate selection:

1. **ALE-Bench** (Imajuku et al., 2025): Long-horizon combinatorial optimization from AtCoder contests (*In-distribution*).

2. **MLE-Bench** (Chan et al., 2025): Autonomous ML engineering across Kaggle competitions (*In-distribution*).

3. **FML-Bench** (Zou et al., 2026): Realistic research codebases covering continual learning, causality, privacy, and robustness (*In-distribution*).

4. **WeatherBench 2** (Rasp et al., 2024): Physics-based forecasting optimization task (*Out-of-distribution*).

#### Table 1: Held-out benchmark results

Measured using mean private contest performance (ALE-Bench), mean private percentile (MLE-Bench), forecast-skill gain (WeatherBench 2), and mean normalized test improvement (FML-Bench). Best score in bold.

| Agent | ALE-Bench | MLE-Bench | WeatherBench 2 | FML-Bench (%) | 
| ----- | ----- | ----- | ----- | ----- | 
| $\text{AIDE}_0$ | $1536 \pm 33$ | $0.678 \pm 0.006$ | $0.262 \pm 0.205$ | $15.0 \pm 0.5$ | 
| $\text{AIDE}_{47}$ | $1713 \pm 26$ | $\mathbf{0.730 \pm 0.005}$ | $\mathbf{0.798 \pm 0.003}$ | $19.7 \pm 1.2$ | 
| $\text{AIDE}_{85}$ | $\mathbf{1790 \pm 9}$ | $0.722 \pm 0.011$ | $0.793 \pm 0.005$ | $\mathbf{19.9 \pm 1.1}$ | 
| $\text{AIDE}_{\text{human}}$ | $1511 \pm 35$ | $0.708 \pm 0.007$ | $0.404 \pm 0.193$ | $19.6 \pm 1.0$ | 

On WeatherBench 2, both evolved checkpoints independently converged on the same family of changes to the forecasting model's numerics on every seed, reaching nearly identical gains with almost no variation across runs.

### 3.4. An emergent behavior: reduced reward hacking

Reward hacking occurs when optimizing an imperfect proxy improves measured performance without a corresponding improvement in the intended objective (Krakovna et al., 2020; Skalse et al., 2022). We evaluated discovered agents on a subset of **KernelBench** (Ouyang et al., 2025), where agents optimize GPU kernels for isolated speedup (the proxy), and evaluated their performance when inserted into real training loops (GPT-2, ViT, CNN):

* $\text{AIDE}_0$: **55%** reward hacking rate

* $\text{AIDE}_{47}$: **39%** reward hacking rate

* $\text{AIDE}_{85}$: **32%** reward hacking rate

* $\text{AIDE}_{\text{human}}$ (baseline): **39%** reward hacking rate

Reward hacking steadily declined along the lineage even though the outer-loop grade never measured or rewarded this behavior.

### 3.5. The self-improved agent: $\text{AIDE}_{85}$

$\text{AIDE}_{85}$ redesigns key components of the baseline $\text{AIDE}_0$:

1. **Search policy:** Runs a bandit policy (Auer et al., 2002) over five fixed drafting strategy arms (`conservative`, `aggressive_rewrite`, `ensemble`, `tuned_specialist`, `robust_simple`). Each step chooses an arm via UCB1, with 30% of steps sampling via softmax over the arms' best scores. Every five search steps, $\text{AIDE}_{85}$ forks the global best node, improving it under a different strategy arm to escape plateaus.

2. **Context management:** Employs bounded, role-specific prompts and a failure memory. When the bug rate reaches $\ge 15\%$, it injects up to three deduplicated recurring error signatures into draft/improve prompts. Compresses prompt sizes dramatically:

   * MLE-Bench: $7\times$ reduction

   * WeatherBench 2: $> 40\times$ reduction

   * ALE-Bench & FML-Bench: $\approx 50\times$ reduction

3. **Robustness:**

   * Fixed instructions reminding the model of unseen private splits.

   * Guard re-prompting if generated code is $< 40$ characters.

   * Candidate selection rule penalizing distance from median of top candidates.

   * Automatically fixed a flaw in a task's evaluation harness where a single test failure crashed the entire test suite.

### 3.6. Ignition test

To determine whether discovered agents are superior at driving recursive self-improvement than their parent improver, we tested $\text{AIDE}_{47}$ in the outer-loop role against $\text{AIDE}_{\text{human}}$ (3 seeds each, 50 outer-loop steps):

* $\text{AIDE}_{47}$ **(Treatment):** Reached final region rapidly ($\approx 20$ steps), ending at mean grade $0.780$.

* $\text{AIDE}_{\text{human}}$ **(Reference):** Progressed gradually ($\approx 40$ steps), ending at mean grade $0.782$.

While $\text{AIDE}_{47}$ demonstrated that it drives recursive self-improvement without performance degradation, the sample size (3 seeds) was insufficient to claim statistically decisive superiority due to cross-loop variance.

## 4. Related Work

* **LLM-driven search:** Single-artifact iteration (Karpathy, 2026), tree search over code (Jiang et al., 2025), population/genetic search (Romera-Paredes et al., 2024; Novikov et al., 2025; Lange et al., 2026).

* **Automated research:** End-to-end science pipelines (Lu et al., 2026; Yamada et al., 2025; Jansen et al., 2025) and benchmarking real research replication (Huang et al., 2024; Starace et al., 2025).

* **Automated harness search:** Prompt optimization and reflective evolution (Pryzant et al., 2023; Khattab et al., 2024; Agrawal et al., 2026b; Yuksekgonul et al., 2025) and harness redesign (Hu et al., 2025; Lee et al., 2026).

* **Self-referential improvement:** Gödel Machines (Schmidhuber, 2007; Zhang et al., 2026a; Wang et al., 2026) and self-modifying coding agents (Zelikman et al., 2024; Robeyns et al., 2025).

* **Meta-learning & learned optimizers:** Learning to optimize via gradient descent (Andrychowicz et al., 2016; Finn et al., 2017) and symbolic optimizer search (Real et al., 2020; Chen et al., 2023).

## 5. Discussion

$\text{AIDE}^2$ demonstrates that recursive self-improvement at the harness layer generates transferable research efficiency gains. It counters diminishing returns by automating the discovery of search mechanisms, context compaction, and robustness safeguards. Key challenges remain:

* **Compounding noise:** Stochasticity in both inner-loop executions and evaluations can lead to falsely accepted candidates.

* **Interpretability and cruft:** Evolved agent codebases accumulate complex, layered behaviors where the marginal utility of individual components can be opaque.

## Appendix

### Table 2: Evaluation protocols per task within each benchmark

| Benchmark | Tasks | Seeds | Cost (\$) | Steps | Time (h) | Model | 
| ----- | ----- | ----- | ----- | ----- | ----- | ----- | 
| **ALE-Bench (lite)** | 10 | 10 | 5 | 200 | 12 | Gemini 3 Flash (Google DeepMind, 2025) | 
| **MLE-Bench (lite)** | 22 | 3 | 5 | 500 | 24 | Gemini 3 Flash (Google DeepMind, 2025) | 
| **WeatherBench 2** | 1 | 3 | 15 | 200 | — | Gemini 3.1 Pro (Google DeepMind, 2026) | 
| **FML-Bench** | 18 | 3 | — | 100 | — | GPT-5.4 (OpenAI, 2026a) | 
| **KernelBench** | 38 pairs | 3 | — | 20 | — | Gemini 3 Flash (Google DeepMind, 2025) | 

### Table 3: Representative rejected proposals from recursive self-improvement trajectories

| What the loop proposed | Related method | $g(a_k) \cdot \Delta g$ | 
| ----- | ----- | ----- | 
| Island populations with periodic migration and crossover | Distributed / island-model GAs (Tanese, 1989; Cantú-Paz, 1998) | $0.685 \; (-0.021)$ | 
| Pairwise LLM-judge tournaments for selection | Tournament selection (Goldberg & Deb, 1991); Pairwise judging (Zheng et al., 2023) | $0.654 \; (-0.090)$ | 
| Stagnation-triggered exploration escalation | Reactive search & adaptive restarts (Battiti et al., 2008) | $0.704 \; (-0.040)$ | 
| Keep-refining vs. restart decisions | Restart policies (Luby et al., 1993) | $0.666 \; (-0.078)$ | 
| Majority-vote ensembles at submission | Bagging (Breiman, 1996); Self-consistency (Wang et al., 2023) | up to $0.723 \; (-0.031)$ (3 variants) | 
| Explore-rate tuning and decay schedules | Decaying $\varepsilon$-greedy exploration (Sutton & Barto, 2018) | $0.748 \; (-0.006)$, within noise | 
| Variance-adaptive exploration boosts | UCB-V (Audibert et al., 2009) | $0.674 \; (-0.080)$ | 
| Ancestor-descendant trend propagation in selection | MCTS value backup (Kocsis & Szepesvári, 2006) | $0.7497 \; (-0.004)$, within noise | 
| Promote-second-best and robust near-tie overrides | Selection under the optimizer's curse (Smith & Winkler, 2006) | 5+ variants, best $-0.007$, within noise | 
| Treating heavy revisits of one node as overfitting suspicion | *No direct analogue identified* | $0.7498 \; (-0.004)$, within noise | 

### Table 4: FML-Bench comparison with existing research agents (from Figure 8)

| Agent | Mean Test Improvement (%) | 
| ----- | ----- | 
| $\text{AIDE}_{\text{human}}$ | $\mathbf{19.6 \pm 1.0}$ | 
| AI Scientist v2\* | $19.3 \pm 1.7$ | 
| Autoresearch\* | $19.2 \pm 1.3$ | 
| AIDE\* | $17.8 \pm 0.7$ | 
| OpenEvolve\* | $15.1 \pm 1.5$ | 
| AI Scientist v1\* | $13.2 \pm 0.1$ | 
| AIRA\* | $13.2 \pm 1.8$ | 

*\* Per-round results provided by FML-Bench authors (Zou et al., 2026).*

### Table 5: Cross-model harness transfer on ALE-Bench and MLE-Bench (from Figure 9, \$20 budget)

| Benchmark | Model | $\text{AIDE}_0$ | $\text{AIDE}_{85}$ | 
| ----- | ----- | ----- | ----- | 
| **ALE-Bench** (score) | Gemini 3 Flash | $1577 \pm 31$ | $1858 \pm 22$ | 
|  | Fable 5 | $1796 \pm 24$ | $1944 \pm 18$ | 
|  | GPT-5.6-Sol | $2025 \pm 31$ | $\mathbf{2121 \pm 17}$ | 
| **MLE-Bench** (percentile) | Gemini 3 Flash | $0.701 \pm 0.015$ | $0.747 \pm 0.007$ | 
|  | GPT-5.6-Sol | $0.767 \pm 0.019$ | $0.794 \pm 0.008$ | 
|  | Fable 5 | $0.823 \pm 0.010$ | $\mathbf{0.828 \pm 0.006}$ | 
