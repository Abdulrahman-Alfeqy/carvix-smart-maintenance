const form = document.querySelector("#chat-form");

if (form) {
    const input = form.querySelector("#chat-message");
    const sendButton = form.querySelector("#chat-send");
    const messages = document.querySelector("#chat-messages");
    const status = document.querySelector("#chat-status");
    const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');

    const appendMessage = (label, value, className) => {
        const entry = document.createElement("p");
        entry.className = className;
        const speaker = document.createElement("strong");
        speaker.textContent = `${label}: `;
        entry.append(speaker, document.createTextNode(value));
        messages.append(entry);
    };

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message || sendButton.disabled) return;

        appendMessage("You", message, "chat-message-user");
        input.value = "";
        input.disabled = true;
        sendButton.disabled = true;
        status.textContent = "Sending…";

        try {
            const response = await fetch(form.dataset.endpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfInput.value,
                },
                body: JSON.stringify({ message }),
            });
            let result;
            try {
                result = await response.json();
            } catch {
                throw new Error("The server returned an unreadable response.");
            }

            if (response.ok && result?.success === true && typeof result?.data?.assistant_message === "string") {
                appendMessage("CARVIX", result.data.assistant_message, "chat-message-assistant");
                status.textContent = "Response received.";
            } else {
                const safeMessage = typeof result?.message === "string"
                    ? result.message
                    : "The message could not be processed.";
                appendMessage("CARVIX", safeMessage, "chat-message-error");
                status.textContent = safeMessage;
            }
        } catch {
            const safeMessage = "The message could not be sent. Check your connection and try again.";
            appendMessage("CARVIX", safeMessage, "chat-message-error");
            status.textContent = safeMessage;
        } finally {
            input.disabled = false;
            sendButton.disabled = false;
            input.focus();
        }
    });
}
