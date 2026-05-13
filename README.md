# SAST
Cutting Security Alert Noise with SLM


## Report
- Paper: https://arxiv.org/pdf/2601.22952v1
    - Summary:
        - Problem addressed
            - Static Application Security Testing (SAST) tools generate large numbers of false positives (FPs), creating heavy manual triage overhead for developers.
        - Core idea
            - Evaluate whether LLM-based agent frameworks can more effectively filter SAST false positives compared to simple (vanilla) prompting approaches. 
        - Agent frameworks studied
            - Aider
            - OpenHands
            - SWE-agent
            - These agents differ in how they perform iterative reasoning, tool usage, and interaction with code and execution environments. 
        - Datasets and benchmarks
            - OWASP Benchmark vulnerabilities
            - Real-world open-source Java projects, including CodeQL alerts. 
        - Key quantitative results
            - On OWASP Benchmark:
                - Initial FP rate of >92% reduced to as low as 6.3% with the best agent configuration. 
            - On real-world projects:
                - Best configuration achieves up to 93.3% FP identification rate for CodeQL alerts. 
        - Model backbone dependence
            - Agentic approaches significantly outperform vanilla prompting when paired with stronger LLM backbones (e.g., Claude Sonnet 4, DeepSeek Chat (vanilla prompting already achieves low FPR), GPT‑5).
            - Gains are limited or inconsistent for weaker backbone models. 
        - Vulnerability-type effects
            - Effectiveness varies by CWE category; some vulnerability classes benefit much more from agent-based reasoning than others. 
            - residual FPs are concentrated in a few categories, particularly CWE-327 (Weak Cryptography), CWE-330 (Weak Randomness), and CWE614 (Secure Cookie Flag), while injection-style vulnerabilities (e.g., CWE-78, CWE-79, CWE-89) are filtered almost completely
        - Trade-offs identified
            - Aggressive FP filtering can suppress true positives, introducing a recall vs. precision trade-off that must be carefully managed. 
        - Cost considerations
            - Large disparities in computational cost across agent frameworks; more sophisticated agents often incur substantially higher execution cost. 
        - Main takeaway
            - LLM-based agents are powerful but non-uniform solutions for SAST false positive filtering.
            - Practical adoption requires careful tuning of agent design, LLM backbone choice, vulnerability category, and cost constraints
    - High-level Archicture Diagram

        ![HDL](./data/architecture_arxiv_2601.22952v1.png)

- OWASP Top 10: 2025 - Target Vulnerabilities:
    - A01:2025 Broken Access Control
    - A05:2025 Injection

- Benchmark dataset: https://owasp.org/www-project-benchmark

- Initial plan
    - Use CodeQL to generate initial alerts - JSON output
    - Run DeepSeek-Coder-V2-Lite (16B) or Qwen 2.5 Coder (14B) - specialized for security code analysis.
    - Triage with Agents using SLM: An AI agent using the SARIF parser to read CodeQL outputs and feed relevant code snippets to an SLM to filter 
    - Benchmark
    
- Other tools (exploration):
    - https://github.com/psyray/oasis
        - Ollama Automated Security Intelligence Scanner
        - An AI-powered security auditing tool that leverages Ollama models to detect and analyze potential security vulnerabilities in your code.
    - https://github.com/OpenHands/OpenHands
    
    - https://openai.com/daybreak/
        - scan -> patch -> validate
        - deploy inside codex security
        - proprietary tool

- Questions:
    - how is the current workflow?
    - the benchmark numbers?
    - deployment?
    - 
