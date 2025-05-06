import React, { useState, useRef, useEffect } from 'react';

export default function App() {
  const backend = import.meta.env.VITE_BACKEND_URL;
  console.log("Using backend:", backend);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const bottomRef = useRef(null);

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Handle sending text
  const handleSend = async e => {
    e.preventDefault();
    if (!input.trim()) return;
    const userMsg = { sender: 'user', text: input.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');

    try {
      const res = await fetch(`${backend}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: userMsg.text })
      });
      const data = await res.json();
      const botMsg = { sender: 'bot', text: data.response };
      setMessages(prev => [...prev, botMsg]);
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, { sender: 'bot', text: 'Error: unable to reach Rubi.' }]);
    }
  };

  // Handle file upload
  const handleFileUpload = async e => {
    const file = e.target.files?.[0];
    if (!file) return;
    const userMsg = { sender: 'user', text: file.name };
    setMessages(prev => [...prev, userMsg]);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch(`${backend}/upload`, {
        method: 'POST',
        body: form,
      });
      const data = await res.json();
      const botMsg = { sender: 'bot', text: data.response };
      setMessages(prev => [...prev, botMsg]);
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, { sender: 'bot', text: 'Error: upload failed.' }]);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-zinc-900">
      {/* Header */}
      <div className="p-4 text-center text-white font-semibold border-b border-zinc-700">Rubi</div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2 bg-zinc-800">
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <span
              className={`max-w-[70%] px-3 py-1 rounded-lg break-words whitespace-pre-line ${msg.sender === 'user' ? 'bg-blue-600 text-white' : 'bg-zinc-700 text-white'}`}
            >
              {msg.text}
            </span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSend}
        className="flex items-center p-4 bg-zinc-900 border-t border-zinc-700"
      >
        <input type="file" onChange={handleFileUpload} className="mr-2" />
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          className="flex-1 bg-zinc-800 text-white p-2 rounded-l outline-none"
          placeholder="Type a message..."
        />
        <button
          type="submit"
          className="bg-blue-500 text-white px-4 py-2 rounded-r hover:bg-blue-600"
        >
          Send
        </button>
      </form>
    </div>
  );
}
