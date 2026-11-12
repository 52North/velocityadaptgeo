# **MCP vs. RAG: Evaluating Agentic Performance Across Paraphrased Prompts for Geospatial Workflows**

## Randy Flores1,2, Benedikt Graeler1 152°North Spatial Information Research GmbH, Muenster, Germany 2Institute for Geoinformatics, University of Muenster, Muenster, Germany

# **Introduction**

	Agentic workflows allow complex tasks to be carried from a natural language prompt. This has broad applicability to allow non-expert users to perform difficult work. To facilitate the agents’ ability to do things beyond text output, tools need to be provided in the form of an API. We examine two ways to expose this interface: A model context protocol (MCP) server which shows all available processes along with metadata, and a vector database populated with the available processes and accessed using retrieval augmented generation (RAG). These two approaches are compared within an agentic system to create a workflow for a geospatial analysis task, and the input prompt is paraphrased in various ways to improve the robustness of the trial.  
	Paraphrases are difficult to formally define but can still be categorized. For example, a sentence can swap words for synonyms or change the order of clauses. Defining different types of paraphrases allows for the identification and creation of paraphrases via a systematic method (Vila et al., 2014). We use six such categories and their subtypes to programmatically generate paraphrases. Paraphrases have been shown to have a noticeable effect on LLM performance (Wahle et al., 2024). By testing many paraphrases, we aim to avoid any influence related to semantics on the outcome of the trial.

# **Methods**

	The paraphrases were generated from a seed prompt that used basic, simplified language. An LLM was given a separate prompt for each type of paraphrase which included instructions and examples from a corpus of paraphrases (Kovatchev et al., 2018). 162 distinct paraphrases were generated from the seed prompt. Each paraphrase was reviewed by both an LLM judge and a human reviewer, and had to meet 8 constraints regarding intention to ensure alignment with the original request.  
	A LangChain agentic workflow generated a workflow graph of geoprocesses with edges denoting data flow. Each paraphrase was used once, and the seed prompt was run 200 times for each variant as a control. The batch script was configured to switch the retrieval method between MCP and RAG with all other nodes of the agentic workflow remaining the same. The workflow graph outputs were grouped and manually evaluated on the basis of accomplishing the user intention, and the quantifiable output of the workflow was checked against a known correct solution. As some parameters were arbitrarily determined by the model, this validation step was solely meant to check that output was correct in a general sense.

# **Findings**

	Paraphrasing had a minor impact on the accuracy of workflow generation and affected both approaches to a similar degree. The MCP approach was consistently more accurate and reliable. Workflow graphs that produced acceptable results but not identical to the correct graph are labeled “lenient” in the results table. MCP retrieval resulted in a significantly larger context and token usage compared to the shortlist of 5 tools from RAG. Quantitative analysis shows that all approved workflow graphs create acceptable results when run with real geoprocesses.

| Variant | Lenient accuracy |  |  | Strict accuracy |  |  | Tokens/req (input/output) |
| ----- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
|  | **Seed** | **Paraphrases** | **All** | **Seed** | **Paraphrases** | **All** |  |
| **MCP** | 95.0% | 95.7% | 95.3% | 93.5% | 90.7% | 92.3% | 191k / 5.2k |
| **RAG** | 89.5% | 81.5% | 85.9% | 27.0% | 27.2% | 27.1% | 88k / 6.3k |

Table 1  
*Results of MCP and RAG trial runs*

# **Conclusion**

	The results show that MCP is a more accurate and reliable solution than RAG, but has the drawback of additional context usage as well as the potential for extra token usage if caching is not implemented. This advantage may decrease as more processes are added to the geoserver, as our example server provided only 25 processes. Paraphrasing did not have a large impact, proving that these systems can handle a variety of distinct inputs. However, so-called extreme paraphrases were not tested and all prompts were required to be grammatically correct. Additionally, the intended workflow had a well-defined correct output and a predictable set of steps to take. Future work could investigate both extreme paraphrases as well as geospatial analysis that has open-ended workflows and results.

# **References**

 	Kovatchev, V., Martí, M. A., & Salamó, M. (2018). ETPC-a paraphrase identification corpus annotated with extended paraphrase typology and negation. *Proceedings of the Eleventh International Conference on Language Resources and Evaluation* (LREC 2018).

	Vila, M., Martí, M. A., & Rodríguez, H. (2014). Is This a Paraphrase? What Kind? Paraphrase Boundaries and Typology. *Open Journal of Modern Linguistics*, 04(01), 205–218. https\://doi.org/10.4236/ojml.2014.41016

	Wahle, J. P., Ruas, T., Xu, Y., & Gipp, B. (2024). Paraphrase Types Elicit Prompt Engineering Capabilities. In Y. Al-Onaizan, M. Bansal, & Y.-N. Chen (Eds.), *Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing* (pp. 11004–11033). Association for Computational Linguistics. https\://doi.org/10.18653/v1/2024.emnlp-main.617

