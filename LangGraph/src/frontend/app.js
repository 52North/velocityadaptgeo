const chat = document.getElementById("chat");
const form = document.getElementById("chat-form");
const input = document.getElementById("prompt");

function addMessage(role, text = "") {
    const div = document.createElement("div");
    div.classList.add("message", role);
    div.textContent = text;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
}

form.addEventListener("submit", (e) => {
    e.preventDefault();

    const prompt = input.value.trim();
    if (!prompt) return;

    addMessage("user", prompt);
    input.value = "";

    let currentStep = null;
    let currentStepMessage = null;

    const evtSource = new EventSource(
        `/api/stream?prompt=${encodeURIComponent(prompt)}`
    );

    evtSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        const step = data.metadata?.langgraph_step;
        const content = data.content;

        if (!step) return;

        // Step changed → reset message reference
        if (step !== currentStep) {
            currentStep = step;
            currentStepMessage = null; // ← key fix
        }

        // Ignore empty content
        if (!content || content === "") return;

        // Create message lazily ONLY when content arrives
        if (!currentStepMessage) {
            currentStepMessage = addMessage(
                "assistant",
                "",
                "streaming step-window"
            );
        }

        // Tool output (object)
        if (typeof content === "object") {
            const pretty = JSON.stringify(content, null, 2);

            currentStepMessage.innerHTML += `
                <details class="tool-output">
                    <summary>🛠 Tool Result (Step ${step})</summary>
                    <pre>${pretty}</pre>
                </details>
            `;
        }
        // Normal token streaming
        else {
            currentStepMessage.innerHTML += content;
        }

        chat.scrollTop = chat.scrollHeight;
    };

    evtSource.onerror = () => {
        evtSource.close();
        if (currentStepMessage) {
            currentStepMessage.classList.remove("streaming");
            currentStepMessage.classList.add("final");
        }
    };
});
