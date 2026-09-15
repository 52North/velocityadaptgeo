# Workflow variant comparison

## Last run per variant
| metric | mcp | pgvector | explanation |
|---|---|---|---|
| runs (failed) | 1 (0) | 1 (0) | recorded turns; failed = turn ended with an error |
| LLM calls | 13.0 | 13.0 | chat model calls in one turn |
| input tokens | 154,665 | 59,556 | input tokens reported by the model, summed over all calls |
| peak input tokens (one call) | 14,323 | 5,874 | largest input of a single call, i.e. the biggest context window |
| output tokens | 2,907 | 2,813 | generated tokens, summed over all calls |
| tool definition tokens | 119,420 | 23,255 | exact tokens of the candidate tool definitions as they appear in the prompts, summed over all calls |
| tool definition share of input | 77% | 39% | tool definition tokens / input tokens, over all runs |
| tool name tokens (defer loading) | 4,116 | 468 | tokens if the prompts carried only the names of the same tools |
| cost USD | 0.1692 | 0.0736 | input and output tokens times the model's price per MTok |
| max visible tools (one call) | 26 | 5 | most candidate tools in a single prompt, over all runs |
| tools per search | 26.0 | 5.0 | candidates returned by one retriever step |
| wall time s | 41.6 | 35.2 | duration of the whole turn |
| unmet capabilities | 0.0 | 0.0 | capabilities no process was found for |

## All prompts
| metric | mcp | pgvector | explanation |
|---|---|---|---|
| runs (failed) | 2 (0) | 1 (0) | recorded turns; failed = turn ended with an error |
| LLM calls | 13.5 | 13.0 | chat model calls in one turn |
| input tokens | 161,741 | 59,556 | input tokens reported by the model, summed over all calls |
| peak input tokens (one call) | 14,325 | 5,874 | largest input of a single call, i.e. the biggest context window |
| output tokens | 2,978 | 2,813 | generated tokens, summed over all calls |
| tool definition tokens | 124,702 | 23,255 | exact tokens of the candidate tool definitions as they appear in the prompts, summed over all calls |
| tool definition share of input | 77% | 39% | tool definition tokens / input tokens, over all runs |
| tool name tokens (defer loading) | 4,288 | 468 | tokens if the prompts carried only the names of the same tools |
| cost USD | 0.1766 | 0.0736 | input and output tokens times the model's price per MTok |
| max visible tools (one call) | 26 | 5 | most candidate tools in a single prompt, over all runs |
| tools per search | 26.0 | 5.0 | candidates returned by one retriever step |
| wall time s | 42.8 | 35.2 | duration of the whole turn |
| unmet capabilities | 0.0 | 0.0 | capabilities no process was found for |

## In Muenster I want to find out which parts of the city are too far from any dece…
| metric | mcp | pgvector | explanation |
|---|---|---|---|
| runs (failed) | 2 (0) | 1 (0) | recorded turns; failed = turn ended with an error |
| LLM calls | 13.5 | 13.0 | chat model calls in one turn |
| input tokens | 161,741 | 59,556 | input tokens reported by the model, summed over all calls |
| peak input tokens (one call) | 14,325 | 5,874 | largest input of a single call, i.e. the biggest context window |
| output tokens | 2,978 | 2,813 | generated tokens, summed over all calls |
| tool definition tokens | 124,702 | 23,255 | exact tokens of the candidate tool definitions as they appear in the prompts, summed over all calls |
| tool definition share of input | 77% | 39% | tool definition tokens / input tokens, over all runs |
| tool name tokens (defer loading) | 4,288 | 468 | tokens if the prompts carried only the names of the same tools |
| cost USD | 0.1766 | 0.0736 | input and output tokens times the model's price per MTok |
| max visible tools (one call) | 26 | 5 | most candidate tools in a single prompt, over all runs |
| tools per search | 26.0 | 5.0 | candidates returned by one retriever step |
| wall time s | 42.8 | 35.2 | duration of the whole turn |
| unmet capabilities | 0.0 | 0.0 | capabilities no process was found for |
