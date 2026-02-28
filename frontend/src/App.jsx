import { useState, useCallback } from 'react'
import ChatbotAssistant from './components/ChatbotAssistant'
import WatchlistButton from './components/WatchlistButton'
import WatchlistPage from './components/WatchlistPage'

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


/* ── SVG micro-icons for OfferCard ─────────────────────────────── */
const TruckSvg = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2" />
        <path d="M15 18H9" /><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14" />
        <circle cx="17" cy="18" r="2" /><circle cx="7" cy="18" r="2" />
    </svg>
)

const ExternalSvg = () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </svg>
)

const StoreSvg = () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7" />
        <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
        <path d="M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4" /><path d="M2 7h20" />
    </svg>
)

function deliveryLabel(offer) {
    if (offer.delivery_days_max != null && offer.delivery_text) {
        return `${offer.delivery_days_max} day${offer.delivery_days_max !== 1 ? 's' : ''} — ${offer.delivery_text}`
    }
    if (offer.delivery_days_max != null) {
        return `${offer.delivery_days_max} day${offer.delivery_days_max !== 1 ? 's' : ''}`
    }
    if (offer.delivery_text) return offer.delivery_text
    if (offer.delivery) return offer.delivery
    return null
}

function discountPct(base, disc) {
    if (base == null || disc == null || base <= disc) return null
    return Math.round(((base - disc) / base) * 100)
}

function OfferCard({ offer, index, currentQuery, currentMode }) {
    const isRecommended = offer.badges?.includes('Recommended')
    const sb = offer.score_breakdown || {}
    const pct = discountPct(offer.base_price, offer.effective_price)
    const delivery = deliveryLabel(offer)
    const productUrl = offer.listing_url || offer.url || ''

    return (
        <div className={`offer-card animate-in ${isRecommended ? 'offer-card--recommended' : ''}`}>
            {/* Header with rank, platform, image */}
            <div className="offer-card__header">
                <div className="offer-card__rank">{offer.rank || index + 1}</div>
                <div style={{ flex: 1 }}>
                    <div className="offer-card__platform"><StoreSvg /> {offer.platform_name}</div>
                    <div className="offer-card__title">{offer.title}</div>
                </div>
                {offer.image_url && (
                    <img className="offer-card__thumb" src={offer.image_url} alt="" loading="lazy" />
                )}
            </div>

            {/* Price + Delivery + Match */}
            <div className="offer-card__body">
                <div className="offer-card__metric">
                    <div className="offer-card__metric-label">Price</div>
                    <div className={`offer-card__metric-value ${offer.effective_price != null ? 'offer-card__price' : 'offer-card__price--null'}`}>
                        {offer.effective_price != null ? formatPrice(offer.effective_price) : 'N/A'}
                    </div>
                    {offer.base_price != null && offer.base_price !== offer.effective_price && (
                        <div className="offer-card__original-price">
                            {formatPrice(offer.base_price)}
                            {pct && <span className="offer-card__discount">-{pct}%</span>}
                        </div>
                    )}
                </div>

                <div className="offer-card__metric">
                    <div className="offer-card__metric-label"><TruckSvg /> Delivery</div>
                    <div className={`offer-card__metric-value offer-card__delivery ${delivery ? '' : 'offer-card__delivery--na'}`}>
                        {delivery || 'Check site'}
                    </div>
                </div>

                <div className="offer-card__metric">
                    <div className="offer-card__metric-label">Match</div>
                    <div className="offer-card__metric-value offer-card__match">
                        {offer.match_score != null ? `${Math.round(offer.match_score * 100)}%` : 'N/A'}
                    </div>
                </div>
            </div>

            {/* Seller + Review row */}
            {(offer.seller_name || offer.review_count != null || offer.seller_rating != null) && (
                <div className="offer-card__meta">
                    {offer.seller_name && <span className="offer-card__seller">Seller: {offer.seller_name}</span>}
                    {offer.seller_rating != null && <span className="offer-card__rating">★ {offer.seller_rating.toFixed(1)}</span>}
                    {offer.review_count != null && <span className="offer-card__reviews">({offer.review_count.toLocaleString('en-IN')} reviews)</span>}
                </div>
            )}

            {/* Footer: badges + CTA */}
            <div className="offer-card__footer">
                {offer.badges?.length > 0 && (
                    <div className="offer-card__badges">
                        {offer.badges.map((badge, i) => (
                            <span key={i} className={`badge ${getBadgeClass(badge)}`}>{badge}</span>
                        ))}
                    </div>
                )}
                {productUrl ? (
                    <a href={productUrl} target="_blank" rel="noopener noreferrer" className="offer-card__cta">
                        View Deal <ExternalSvg />
                    </a>
                ) : (
                    <span className="offer-card__cta offer-card__cta--disabled">
                        No link available
                    </span>
                )}
                <WatchlistButton offer={offer} currentQuery={currentQuery} currentMode={currentMode} />
            </div>

            {/* Score breakdown bars */}
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
    const [showWatchlist, setShowWatchlist] = useState(false)
    const [currentQuery, setCurrentQuery] = useState('')
    const [currentMode, setCurrentMode] = useState('balanced')

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

        setCurrentQuery(query.trim())
        setCurrentMode(mode)

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
                <button
                    className="watchlist-nav-btn"
                    onClick={() => setShowWatchlist(!showWatchlist)}
                >
                    {showWatchlist ? '🔍 Search' : '🔔 Watchlist'}
                </button>
            </header>

            {showWatchlist && (
                <WatchlistPage onBack={() => setShowWatchlist(false)} />
            )}

            {!showWatchlist && <>
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
                                    <OfferCard key={i} offer={offer} index={i} currentQuery={currentQuery} currentMode={currentMode} />
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
            </>}
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
