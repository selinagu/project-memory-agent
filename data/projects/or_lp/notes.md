# OR LP Notes

Goal:
Study an online selection-over-time problem under a refined running-maximum benchmark. Formulate and solve DP/LP versions of the problem, compare optimal policies, and analyze whether the LP/dual structure can lead to theoretical guarantees.

Problem Setup:
- There are n unknown values U_1 >= ... >= U_n.
- Values arrive in uniformly random order.
- At each time t, the decision-maker observes the partial rank s of the current arrival among the first t arrivals.
- The decision-maker may choose a holding duration a in {1, ..., n - t + 1}.
- If selected, the reward is the chosen value multiplied by the holding time.
- During the holding period, future arrivals are blocked.
- The benchmark is the expected running maximum:
  OPT = E_omega[sum_{t=1}^n max(U_{omega(1)}, ..., U_{omega(t)})].

Background:
- Previous work on online selection over time used a different benchmark nu_1 and obtained an asymptotic STS-F ratio around 0.16190.
- This project replaces that benchmark with the running-maximum benchmark.
- For STS-F under the refined benchmark, asymptotic analysis suggests a tight ratio around 0.324, with the binding case at rank i = 1.

DP Progress:
- Implemented an exact dynamic programming formulation with state (t, s), where t is time and s is partial rank.
- Actions are holding durations a in {1, ..., n - t + 1}.
- The DP was tested on linear sequences, exponential sequences U_i = epsilon^i, and top-only sequences where U_1 = 1 and all others are 0.
- DP results show that intermediate holding actions exist but are rare for linear sequences.
- For n = 500 linear values, there were 123 intermediate states out of 125250 total states, about 0.098%.
- For slow-decay exponential sequences such as epsilon = 0.95, the optimal policy depends on partial ranks beyond the current record.
- For fast-decay exponential sequences such as epsilon <= 0.5, the policy becomes closer to record-only.
- For top-only sequences, the policy is record-only in the sense that non-record states are not useful, but intermediate holding durations within record states can still improve value.

LP Progress:
- Formulated a primal occupancy-measure LP based on the DP.
- Variables z[(t, s, a)] represent state-action occupancy mass.
- The LP has flow conservation constraints over states and benchmark constraints indexed by rank i.
- The objective is to maximize the competitive ratio rho.
- Numerical validation shows that the LP objective matches the DP value.
- The LP policy recovered from positive z variables matches the DP policy.
- Gurobi can solve the primal LP and also provide dual variable information for constraints.

Dual Progress:
- Formulated the dual of the competitive-ratio LP.
- The main dual variables are h and lambda.
- Numerical checks show that the dual objective matches the primal objective on tested instances.
- The dual formulation appears consistent with the primal formulation.
- Current analysis is focused on interpreting the dual variables and proving structural lemmas.

Confirmed Numerical Findings:
- DP and primal LP results match on tested instances.
- LP policy and DP policy match on tested instances.
- Dual and primal objectives match in numerical verification.
- Binding cases often appear at i = 1 in numerical experiments.
- Intermediate actions exist but are rare for linear sequences.
- For slow-decay exponential sequences, non-record partial ranks can matter.
- For top-only sequences, non-record states are not useful, but intermediate holding at record states can still be useful.

Advisor / PhD Feedback:
- The advisor recommended the DP-to-LP route inspired by Perez-Salazar, Singh, and Toriello.
- The project should derive a primal LP from the DP, then derive and analyze the dual.
- A useful next goal is to understand whether the dual can certify the competitive ratio and reveal policy structure.
- There is interest in explaining why binding cases appear at i = 1.

Current Status:
DP formulation, primal LP formulation, and dual LP formulation have been implemented and numerically validated. The current stage is dual interpretation and theoretical analysis.

Open Questions:
- How should the dual variables h and lambda be interpreted?
- Can the dual variables be used to prove structural properties of the optimal policy?
- Can the observed binding case at i = 1 be proved theoretically?
- Do Lemma 2, Lemma 3, and Lemma 4 together imply a tight competitive ratio?
- Is V(1,1) directly computable or only useful as an implicit certificate?
- What is the best next theoretical target: solve the dual, prove policy structure, or prove the binding i = 1 phenomenon?

Next Actions:
- Interpret the meaning of the dual variables h and lambda.
- Continue proving the proposed structural lemmas for the dual.
- Clarify whether the lemmas imply that V(1,1) gives the tight competitive ratio.
- Investigate whether the binding i = 1 phenomenon can be proved rather than only observed numerically.
- Decide whether to focus first on solving the dual or proving structural properties of the optimal policy.

Failed / Blocked Attempts:
- No major implementation failure is currently unresolved.
- The main difficulty is theoretical: understanding and proving useful properties of the dual formulation.
