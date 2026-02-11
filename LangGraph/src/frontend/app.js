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

    const assistantMsg = addMessage("assistant", "");

    const evtSource = new EventSource(
        `/api/stream?prompt=${encodeURIComponent(prompt)}`
    );

    evtSource.onmessage = (event) => {
        const chunk = JSON.parse(event.data);

        // adjust depending on structure
        assistantMsg.textContent += JSON.stringify(chunk);
    };

    evtSource.onerror = () => {
        evtSource.close();
    };
});

