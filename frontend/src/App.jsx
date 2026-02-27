import { useState, useCallback } from 'react'
import ChatbotAssistant from './components/ChatbotAssistant'

const API_BASE = ''  // Proxied via vite.config.js

const MODES = [
    { key: 'balanced', label: 'Balanced', icon: '⚖️' },
    { key: 'cheapest', label: 'Cheapest', icon: '💰' },
    { key: 'fastest', label: 'Fastest', icon: '⚡' },
    { key: 'reliable', label: 'Most Reliable', icon: '🛡️' },
]

function formatPrice(price) {
    if (price == null) return null
    return `Rs. ${Number(price).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function getBadgeClass(badge) {
    const b = badge.toLowerCase()
    if (b.includes('recommend')) return 'badge--recommended'
    if (b.includes('price')) return 'badge--best-price'
    if (b.includes('fast')) return 'badge--fastest'
    if (b.includes('trust')) return 'badge--trusted'
    return 'badge--recommended'
}

function getStatusDotClass(status) {
    if (status === 'ok') return 'site-status__dot--ok'
    if (status === 'error') return 'site-status__dot--error'
    if (status === 'timeout') return 'site-status__dot--timeout'
    if (status === 'bot_challenge') return 'site-status__dot--bot'
    if (status === 'no_results') return 'site-status__dot--no_results'
    return 'site-status__dot--pending'
}


function OfferCard({ offer, index }) {
    const isRecommended = offer.badges?.includes('Recommended')
    const sb = offer.score_breakdown || {}

    return (
        <div className={`offer-card animate-in ${isRecommended ? 'offer-card--recommended' : ''}`}>
            <div className="offer-card__header">
                <div className="offer-card__rank">{offer.rank || index + 1}</div>
                <div style={{ flex: 1 }}>
                    <div className="offer-card__platform">{offer.platform_name}</div>
                    <div className="offer-card__title">{offer.title}</div>
                </div>
            </div>

            <div className="offer-card__body">
                <div className="offer-card__metric">
                    <div className="offer-card__metric-label">Price</div>
                    <div className={`offer-card__metric-value ${offer.effective_price != null ? 'offer-card__price' : 'offer-card__price--null'}`}>
                        {offer.effective_price != null ? formatPrice(offer.effective_price) : 'N/A'}
                    </div>
                    {offer.base_price != null && offer.base_price !== offer.effective_price && (
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', textDecoration: 'line-through' }}>
                            {formatPrice(offer.base_price)}
                        </div>
                    )}
                </div>

                <div className="offer-card__metric">
                    <div className="offer-card__metric-label">Delivery</div>
                    <div className="offer-card__metric-value offer-card__delivery">
                        {offer.delivery_days_max != null
                            ? `${offer.delivery_days_max} day${offer.delivery_days_max !== 1 ? 's' : ''}`
                            : offer.delivery_text || 'N/A'}
                    </div>
                </div>

                <div className="offer-card__metric">
                    <div className="offer-card__metric-label">Match</div>
                    <div className="offer-card__metric-value offer-card__match">
                        {offer.match_score != null ? `${Math.round(offer.match_score * 100)}%` : 'N/A'}
                    </div>
                </div>
            </div>

            <div className="offer-card__footer">
                {offer.badges?.length > 0 && (
                    <div className="offer-card__badges">
                        {offer.badges.map((badge, i) => (
                            <span key={i} className={`badge ${getBadgeClass(badge)}`}>{badge}</span>
                        ))}
                    </div>
                )}
                {(offer.listing_url || offer.url) ? (
                    <a href={offer.listing_url || offer.url} target="_blank" rel="noopener noreferrer" className="offer-card__link">
                        View Deal →
                    </a>
                ) : (
                    <span className="offer-card__link offer-card__link--disabled" style={{ opacity: 0.4, cursor: 'default' }}>
                        No link available
                    </span>
                )}
            </div>

            {(sb.price_score != null || sb.delivery_score != null || sb.trust_score != null) && (
                <div className="score-bar">
                    <ScoreRow label="Price" value={sb.price_score} variant="price" />
                    <ScoreRow label="Delivery" value={sb.delivery_score} variant="delivery" />
                    <ScoreRow label="Trust" value={sb.trust_score} variant="trust" />
                </div>
            )}
        </div>
    )
}


function ScoreRow({ label, value, variant }) {
    if (value == null) return null
    const pct = Math.round(value * 100)
    return (
        <div className="score-bar__row">
            <span className="score-bar__label">{label}</span>
            <div className="score-bar__track">
                <div
                    className={`score-bar__fill score-bar__fill--${variant}`}
                    style={{ width: `${pct}%` }}
                />
            </div>
            <span className="score-bar__value">{pct}%</span>
        </div>
    )
}


function App() {
    const [query, setQuery] = useState('')
    const [mode, setMode] = useState('balanced')
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState(null)
    const [error, setError] = useState(null)
    const [elapsed, setElapsed] = useState(0)
    const [progress, setProgress] = useState(null) // SSE progress tracking

    const handleSearch = useCallback(async (e) => {
        e.preventDefault()
        if (!query.trim() || loading) return

        setLoading(true)
        setError(null)
        setResult(null)
        setProgress(null)

        const startTime = Date.now()
        const timer = setInterval(() => {
            setElapsed(Math.round((Date.now() - startTime) / 1000))
        }, 1000)

        try {
            const response = await fetch(`${API_BASE}/api/compare`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: query.trim(),
                    mode,
                    preferences: { mode, min_match_score: 0.4 },
                }),
            })

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}))
                throw new Error(errData.detail || `Server error: ${response.status}`)
            }

            const contentType = response.headers.get('content-type') || ''

            if (contentType.includes('text/event-stream')) {
                // ── SSE streaming mode ──
                const reader = response.body.getReader()
                const decoder = new TextDecoder()
                let buffer = ''
                const siteStatuses = []
                let matchedCount = 0
                let rankedCount = 0

                while (true) {
                    const { value, done } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const parts = buffer.split('\n\n')
                    buffer = parts.pop() || ''

                    for (const part of parts) {
                        if (!part.trim()) continue
                        const eventMatch = part.match(/event:\s*(\S+)\ndata:\s*(.+)/s)
                        if (!eventMatch) continue
                        const [, eventType, dataStr] = eventMatch

                        let data
                        try { data = JSON.parse(dataStr) } catch { continue }

                        if (eventType === 'scraping_started') {
                            setProgress({ stage: 'scraping', sites: data.sites || [], completedSites: [] })

                        } else if (eventType === 'site_done') {
                            siteStatuses.push(data)
                            setProgress((prev) => ({
                                ...prev,
                                stage: 'scraping',
                                completedSites: [...(prev?.completedSites || []), data.marketplace_key || data.site || ''],
                            }))

                        } else if (eventType === 'matching_done') {
                            matchedCount = data.matched_count || 0
                            setProgress((prev) => ({ ...prev, stage: 'matching', matchedCount }))

                        } else if (eventType === 'ranking_done') {
                            rankedCount = data.ranked_count || 0
                            setProgress((prev) => ({ ...prev, stage: 'ranking', rankedCount }))

                        } else if (eventType === 'final_result') {
                            // Build a result object compatible with existing UI
                            const finalResult = {
                                final_offers: data.ranked_offers || [],
                                site_statuses: data.site_statuses || siteStatuses,
                                explanation: data.explanation || '',
                                best_deal: data.best_deal,
                                total_offers_found: (data.ranked_offers || []).length,
                                query_time_seconds: data.query_time_seconds || Math.round((Date.now() - startTime) / 1000),
                                normalized_product: data.normalized_product,
                            }
                            setResult(finalResult)

                        } else if (eventType === 'error') {
                            throw new Error(data.error || 'Pipeline error')
                        }
                    }
                }
            } else {
                // ── JSON fallback (backward-compatible) ──
                const data = await response.json()
                setResult(data)
            }
        } catch (err) {
            setError(err.message || 'Failed to connect to the backend. Is the server running?')
        } finally {
            clearInterval(timer)
            setLoading(false)
            setProgress(null)
        }
    }, [query, mode, loading])

    return (
        <div className="app">
            {/* Header */}
            <header className="header">
                <div className="header__logo">
                    <div className="header__icon">🔍</div>
                    <h1 className="header__title">AI Price Comparison</h1>
                </div>
                <p className="header__subtitle">
                    AI-powered price comparison across 10+ Indian e-commerce marketplaces
                </p>
            </header>

            {/* Search */}
            <section className="search">
                <form className="search__form" onSubmit={handleSearch}>
                    <input
                        id="search-input"
                        className="search__input"
                        type="text"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search any product... e.g. Samsung Galaxy S24 128GB"
                        disabled={loading}
                    />
                    <button
                        id="search-button"
                        className={`search__button ${loading ? 'search__button--loading' : ''}`}
                        type="submit"
                        disabled={loading || !query.trim()}
                    >
                        {loading ? `Searching... ${elapsed}s` : 'Compare Prices'}
                    </button>
                </form>

                <div className="preferences">
                    {MODES.map((m) => (
                        <button
                            key={m.key}
                            className={`pref-chip ${mode === m.key ? 'pref-chip--active' : ''}`}
                            onClick={() => setMode(m.key)}
                            type="button"
                        >
                            {m.icon} {m.label}
                        </button>
                    ))}
                </div>
            </section>

            {/* Loading with live progress */}
            {loading && (
                <div className="loading">
                    <div className="loading__spinner" />
                    {progress?.stage === 'scraping' ? (
                        <>
                            <div className="loading__text">
                                Scraping marketplaces... ({progress.completedSites?.length || 0}/{progress.sites?.length || '?'})
                            </div>
                            <div className="loading__subtext">
                                {progress.completedSites?.length > 0
                                    ? `Done: ${progress.completedSites.join(', ')}`
                                    : 'Launching browsers, extracting prices...'}
                            </div>
                        </>
                    ) : progress?.stage === 'matching' ? (
                        <>
                            <div className="loading__text">Matching products...</div>
                            <div className="loading__subtext">{progress.matchedCount} offers matched so far</div>
                        </>
                    ) : progress?.stage === 'ranking' ? (
                        <>
                            <div className="loading__text">Ranking offers...</div>
                            <div className="loading__subtext">{progress.rankedCount} offers ranked</div>
                        </>
                    ) : (
                        <>
                            <div className="loading__text">Scraping {mode === 'balanced' ? 'all' : ''} marketplaces...</div>
                            <div className="loading__subtext">Launching browsers, extracting prices, matching products</div>
                        </>
                    )}
                    <div className="loading__elapsed">{elapsed}s</div>
                </div>
            )}

            {/* Error */}
            {error && !loading && (
                <div className="errors">
                    <div className="error-item">⚠️ {error}</div>
                </div>
            )}

            {/* Results */}
            {result && !loading && (
                <div>
                    {/* Summary */}
                    <div className="results-summary">
                        <div className="results-summary__title">
                            {result.normalized_product?.attributes?.brand}{' '}
                            {result.normalized_product?.attributes?.model}{' '}
                            {result.normalized_product?.attributes?.storage || ''}
                        </div>
                        <div className="results-summary__stats">
                            <div className="results-summary__stat">
                                <div className="results-summary__stat-value">{result.total_offers_found || 0}</div>
                                <div className="results-summary__stat-label">Offers</div>
                            </div>
                            <div className="results-summary__stat">
                                <div className="results-summary__stat-value">
                                    {result.site_statuses?.filter((s) => s.listings_found > 0).length || 0}
                                </div>
                                <div className="results-summary__stat-label">Sites</div>
                            </div>
                            <div className="results-summary__stat">
                                <div className="results-summary__stat-value">
                                    {result.query_time_seconds ? `${result.query_time_seconds}s` : '--'}
                                </div>
                                <div className="results-summary__stat-label">Time</div>
                            </div>
                        </div>
                    </div>

                    {/* AI Explanation */}
                    {result.explanation && (
                        <div className="explanation">
                            <div className="explanation__title">
                                <span className="explanation__icon">🤖</span> AI Recommendation
                            </div>
                            <div className="explanation__text">{result.explanation}</div>
                        </div>
                    )}

                    {/* Site Statuses — only show sites that have offers */}
                    {result.site_statuses?.length > 0 && (
                        <div className="site-statuses">
                            <div className="site-statuses__title">Marketplace Status</div>
                            <div className="site-statuses__grid">
                                {result.site_statuses
                                    .filter((s) => s.listings_found > 0 || s.status === 'ok')
                                    .map((s, i) => (
                                        <div key={i} className="site-status">
                                            <div className={`site-status__dot ${getStatusDotClass(s.status)}`} />
                                            <span className="site-status__name">{s.marketplace_name || s.marketplace_key}</span>
                                            {s.listings_found > 0 && (
                                                <span className="site-status__count">({s.listings_found})</span>
                                            )}
                                        </div>
                                    ))}
                            </div>
                        </div>
                    )}

                    {/* Pipeline Errors */}
                    {result.errors?.length > 0 && (
                        <div className="errors">
                            {result.errors.map((err, i) => (
                                <div key={i} className="error-item">⚠️ {err}</div>
                            ))}
                        </div>
                    )}

                    {/* Offer Cards */}
                    {result.final_offers?.length > 0 ? (
                        <div className="offers-grid">
                            {result.final_offers.map((offer, i) => (
                                <OfferCard key={i} offer={offer} index={i} />
                            ))}
                        </div>
                    ) : (
                        <div className="empty-state">
                            <div className="empty-state__icon">📭</div>
                            <div className="empty-state__title">No matching offers found</div>
                            <div className="empty-state__text">
                                Try a different product or broader search terms. Some sites may be temporarily blocked.
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Initial Empty State */}
            {!result && !loading && !error && (
                <div className="empty-state">
                    <div className="empty-state__icon">🛒</div>
                    <div className="empty-state__title">Find the best price across India</div>
                    <div className="empty-state__text">
                        Search for any product to compare prices across Amazon, Flipkart, Croma, Meesho, and more.
                    </div>
                </div>
            )}
        </div>
    )
}

function AppWithChatbot() {
    return (
        <>
            <App />
            <ChatbotAssistant />
        </>
    )
}

export default AppWithChatbot
