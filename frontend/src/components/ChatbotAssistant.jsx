import { useState, useRef, useEffect, useCallback } from 'react'

const API_BASE = '' // Proxied via vite.config.js

/* ── SVG Icons (inline, no external dependency) ────────────────── */

const BotIcon = () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 8V4H8" /><rect width="16" height="12" x="4" y="8" rx="2" />
        <path d="M2 14h2" /><path d="M20 14h2" /><path d="M15 13v2" /><path d="M9 13v2" />
    </svg>
)

const SendIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" />
    </svg>
)

const StarIcon = () => (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
)

const ExternalLinkIcon = () => (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </svg>
)

const CloseIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 6 6 18" /><path d="m6 6 12 12" />
    </svg>
)

const ChevronDownIcon = () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m6 9 6 6 6-6" />
    </svg>
)

/* ── Product Card inside assistant message ─────────────────────── */

function ProductCard({ product }) {
    return (
        <div className="cb-product-card">
            {product.thumbnail && (
                <div className="cb-product-card__img">
                    <img src={product.thumbnail} alt={product.title} loading="lazy" />
                </div>
            )}
            <div className="cb-product-card__info">
                <div className="cb-product-card__title">{product.title}</div>
                <div className="cb-product-card__meta">
                    {product.price && (
                        <span className="cb-product-card__price">{product.price}</span>
                    )}
                    {product.rating != null && (
                        <span className="cb-product-card__rating">
                            <StarIcon /> {product.rating}
                        </span>
                    )}
                    {product.source && (
                        <span className="cb-product-card__source">{product.source}</span>
                    )}
                </div>
                {product.link && (
                    <a
                        href={product.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="cb-product-card__link"
                    >
                        View Deal <ExternalLinkIcon />
                    </a>
                )}
            </div>
        </div>
    )
}

/* ── Typing indicator ──────────────────────────────────────────── */

function TypingIndicator() {
    return (
        <div className="cb-typing">
            <span /><span /><span />
        </div>
    )
}

/* ── Main ChatbotAssistant Component ───────────────────────────── */

export default function ChatbotAssistant() {
    const [isOpen, setIsOpen] = useState(false)
    const [messages, setMessages] = useState([
        {
            role: 'assistant',
            content: 'Hi! 👋 I\'m your shopping assistant. Ask me about any product, price, or comparison and I\'ll help you find the best deals across India!',
            products: [],
        },
    ])
    const [inputValue, setInputValue] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [error, setError] = useState(null)
    const messagesEndRef = useRef(null)
    const inputRef = useRef(null)

    // Auto-scroll to bottom on new message
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages, isLoading])

    // Focus input when chat opens
    useEffect(() => {
        if (isOpen) {
            setTimeout(() => inputRef.current?.focus(), 100)
        }
    }, [isOpen])

    const handleSend = useCallback(async () => {
        const trimmed = inputValue.trim()
        if (!trimmed || isLoading) return

        setError(null)

        // Append user message
        const userMsg = { role: 'user', content: trimmed, products: [] }
        setMessages((prev) => [...prev, userMsg])
        setInputValue('')
        setIsLoading(true)

        try {
            // Build chat_history from last 4 messages (excluding the one we just added)
            const allMessages = [...messages, userMsg]
            const chatHistory = allMessages.slice(-4).map((m) => ({
                role: m.role,
                content: m.content,
            }))

            const response = await fetch(`${API_BASE}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: trimmed,
                    chat_history: chatHistory,
                }),
            })

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}))
                throw new Error(errData.detail || `Server error: ${response.status}`)
            }

            const data = await response.json()

            const assistantMsg = {
                role: 'assistant',
                content: data.message || 'Sorry, I couldn\'t generate a response.',
                products: data.products || [],
            }
            setMessages((prev) => [...prev, assistantMsg])
        } catch (err) {
            setError(err.message || 'Failed to connect. Is the server running?')
            setMessages((prev) => [
                ...prev,
                {
                    role: 'assistant',
                    content: 'Sorry, I had trouble connecting. Please try again.',
                    products: [],
                },
            ])
        } finally {
            setIsLoading(false)
        }
    }, [inputValue, isLoading, messages])

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSend()
        }
    }

    return (
        <>
            {/* Floating Action Button */}
            {!isOpen && (
                <button className="cb-fab" onClick={() => setIsOpen(true)} title="Open Shopping Assistant">
                    <BotIcon />
                    <span className="cb-fab__pulse" />
                </button>
            )}

            {/* Chat Window */}
            {isOpen && (
                <div className="cb-window">
                    {/* Header */}
                    <div className="cb-header">
                        <div className="cb-header__left">
                            <div className="cb-header__icon"><BotIcon /></div>
                            <div>
                                <div className="cb-header__title">Shopping Assistant</div>
                                <div className="cb-header__subtitle">Powered by Google Shopping + AI</div>
                            </div>
                        </div>
                        <div className="cb-header__actions">
                            <button className="cb-header__btn" onClick={() => setIsOpen(false)} title="Minimize">
                                <ChevronDownIcon />
                            </button>
                        </div>
                    </div>

                    {/* Messages */}
                    <div className="cb-messages">
                        {messages.map((msg, i) => (
                            <div key={i} className={`cb-msg cb-msg--${msg.role}`}>
                                <div className={`cb-msg__bubble cb-msg__bubble--${msg.role}`}>
                                    {msg.content}
                                </div>
                                {msg.role === 'assistant' && msg.products?.length > 0 && (
                                    <div className="cb-products">
                                        {msg.products.map((product, j) => (
                                            <ProductCard key={j} product={product} />
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                        {isLoading && (
                            <div className="cb-msg cb-msg--assistant">
                                <div className="cb-msg__bubble cb-msg__bubble--assistant">
                                    <TypingIndicator />
                                </div>
                            </div>
                        )}
                        <div ref={messagesEndRef} />
                    </div>

                    {/* Error */}
                    {error && (
                        <div className="cb-error">
                            ⚠️ {error}
                            <button onClick={() => setError(null)} className="cb-error__close">
                                <CloseIcon />
                            </button>
                        </div>
                    )}

                    {/* Input */}
                    <div className="cb-input-bar">
                        <input
                            ref={inputRef}
                            className="cb-input"
                            type="text"
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Ask about any product..."
                            disabled={isLoading}
                            maxLength={500}
                        />
                        <button
                            className="cb-send-btn"
                            onClick={handleSend}
                            disabled={isLoading || !inputValue.trim()}
                            title="Send"
                        >
                            <SendIcon />
                        </button>
                    </div>
                </div>
            )}
        </>
    )
}
