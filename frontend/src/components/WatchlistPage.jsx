import { useState, useEffect, useCallback } from 'react'

const API_BASE = ''

/* ── Helpers ──────────────────────────────────────────────────────────────── */

function timeAgo(dateStr) {
    if (!dateStr) return 'never'
    const diff = Date.now() - new Date(dateStr).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    return `${days}d ago`
}

function formatPrice(p) {
    if (p == null) return 'N/A'
    return `₹${Number(p).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function priceBadge(saved, current) {
    if (saved == null || current == null) return { label: '—', cls: 'unchanged' }
    if (current < saved) {
        const pct = Math.round(((saved - current) / saved) * 100)
        return { label: `↓ ${pct}% cheaper`, cls: 'cheaper' }
    }
    if (current > saved) {
        const pct = Math.round(((current - saved) / saved) * 100)
        return { label: `↑ ${pct}% pricier`, cls: 'pricier' }
    }
    return { label: 'Unchanged', cls: 'unchanged' }
}

/* ── Loading Skeleton ─────────────────────────────────────────────────────── */

function WatchlistSkeleton() {
    return (
        <div className="watchlist-grid">
            {[1, 2, 3].map((i) => (
                <div key={i} className="watchlist-card watchlist-card--skeleton">
                    <div className="skeleton-thumb" />
                    <div className="skeleton-line skeleton-line--long" />
                    <div className="skeleton-line skeleton-line--short" />
                    <div className="skeleton-line skeleton-line--medium" />
                </div>
            ))}
        </div>
    )
}

/* ── Watchlist Card ───────────────────────────────────────────────────────── */

function WatchlistCard({ item, onRemove, onCheckNow, onViewHistory }) {
    const [checking, setChecking] = useState(false)
    const badge = priceBadge(item.saved_price, item.current_price)

    const handleCheck = async () => {
        setChecking(true)
        await onCheckNow(item.id)
        setChecking(false)
    }

    return (
        <div className="watchlist-card">
            {/* Thumbnail */}
            <div className="watchlist-card__img-wrap">
                {item.thumbnail_url ? (
                    <img src={item.thumbnail_url} alt="" className="watchlist-card__img" loading="lazy" />
                ) : (
                    <div className="watchlist-card__img-placeholder">📦</div>
                )}
            </div>

            {/* Content */}
            <div className="watchlist-card__body">
                <div className="watchlist-card__site">{item.site}</div>
                <div className="watchlist-card__title">{item.product_title}</div>

                <div className="watchlist-card__prices">
                    <span className="watchlist-card__saved-price">Saved: {formatPrice(item.saved_price)}</span>
                    <span className="watchlist-card__current-price">Current: {formatPrice(item.current_price)}</span>
                </div>

                <span className={`price-badge price-badge--${badge.cls}`}>{badge.label}</span>

                <div className="watchlist-card__meta">
                    <span>Alert: ≥{item.alert_threshold}% drop</span>
                    <span>Checked: {timeAgo(item.last_checked)}</span>
                </div>
            </div>

            {/* Actions */}
            <div className="watchlist-card__actions">
                {item.product_url && (
                    <a
                        href={item.product_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="watchlist-card__action-btn watchlist-card__action-btn--primary"
                    >
                        View Deal
                    </a>
                )}
                <button
                    className="watchlist-card__action-btn watchlist-card__action-btn--secondary"
                    onClick={handleCheck}
                    disabled={checking}
                >
                    {checking ? 'Checking…' : '🔄 Check Now'}
                </button>
                <button
                    className="watchlist-card__action-btn watchlist-card__action-btn--ghost"
                    onClick={() => onViewHistory(item.id)}
                >
                    📊 History
                </button>
                <button
                    className="watchlist-card__action-btn watchlist-card__action-btn--danger"
                    onClick={() => onRemove(item.id)}
                >
                    🗑 Remove
                </button>
            </div>
        </div>
    )
}

/* ── Price History Modal ──────────────────────────────────────────────────── */

function PriceHistoryModal({ data, onClose }) {
    if (!data) return null
    const { item, history } = data

    return (
        <div className="watchlist-modal-overlay" onClick={onClose}>
            <div className="watchlist-modal-card watchlist-modal-card--wide" onClick={(e) => e.stopPropagation()}>
                <div className="watchlist-modal-card__header">
                    <h3>Price History — {item.product_title}</h3>
                    <button className="watchlist-modal-card__close" onClick={onClose}>✕</button>
                </div>

                <div className="watchlist-modal-card__site" style={{ marginBottom: 12 }}>
                    {item.site} · Saved at {formatPrice(item.saved_price)}
                </div>

                {history.length === 0 ? (
                    <div className="watchlist-history-empty">No price history yet. Prices are checked periodically.</div>
                ) : (
                    <div className="watchlist-history-table-wrap">
                        <table className="watchlist-history-table">
                            <thead>
                                <tr>
                                    <th>Date</th>
                                    <th>Price</th>
                                    <th>In Stock</th>
                                    <th>vs Saved</th>
                                </tr>
                            </thead>
                            <tbody>
                                {history.slice().reverse().map((pt, i) => {
                                    const badge = priceBadge(item.saved_price, pt.price)
                                    return (
                                        <tr key={i}>
                                            <td>{new Date(pt.checked_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</td>
                                            <td>{formatPrice(pt.price)}</td>
                                            <td>{pt.in_stock ? '✅' : '❌'}</td>
                                            <td><span className={`price-badge price-badge--${badge.cls}`}>{badge.label}</span></td>
                                        </tr>
                                    )
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    )
}

/* ── Main WatchlistPage ───────────────────────────────────────────────────── */

export default function WatchlistPage({ onBack }) {
    const [email, setEmail] = useState(() => localStorage.getItem('wl_email') || '')
    const [submitted, setSubmitted] = useState(() => !!localStorage.getItem('wl_email'))
    const [items, setItems] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [historyModal, setHistoryModal] = useState(null)
    const [toast, setToast] = useState(null)

    const showToast = (msg, type = 'success') => {
        setToast({ msg, type })
        setTimeout(() => setToast(null), 3000)
    }

    const fetchItems = useCallback(async (e_mail) => {
        setLoading(true)
        setError(null)
        try {
            const res = await fetch(`${API_BASE}/api/watchlist/${encodeURIComponent(e_mail)}`)
            if (!res.ok) throw new Error('Failed to load watchlist')
            const data = await res.json()
            setItems(data.items || [])
        } catch (err) {
            setError(err.message)
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        if (submitted && email) fetchItems(email)
    }, [submitted, email, fetchItems])

    const handleEmailSubmit = (e) => {
        e.preventDefault()
        if (!email.trim()) return
        localStorage.setItem('wl_email', email.trim())
        setSubmitted(true)
        fetchItems(email.trim())
    }

    const handleRemove = async (itemId) => {
        try {
            const res = await fetch(`${API_BASE}/api/watchlist/remove`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ item_id: itemId, user_email: email }),
            })
            if (!res.ok) throw new Error('Failed to remove')
            setItems((prev) => prev.filter((it) => it.id !== itemId))

            // Clean up localStorage saved keys
            const savedKeys = JSON.parse(localStorage.getItem('wl_saved') || '{}')
            const updated = {}
            for (const [k, v] of Object.entries(savedKeys)) {
                if (!k.startsWith(`${email}::`)) updated[k] = v
                else {
                    // Keep entries not matching the removed item
                    const item = items.find(it => it.id === itemId)
                    if (item && k === `${email}::${item.product_url}`) continue
                    updated[k] = v
                }
            }
            localStorage.setItem('wl_saved', JSON.stringify(updated))
            showToast('Item removed from watchlist')
        } catch (err) {
            showToast(err.message, 'error')
        }
    }

    const handleCheckNow = async (itemId) => {
        try {
            const res = await fetch(
                `${API_BASE}/api/watchlist/${itemId}/check-now?user_email=${encodeURIComponent(email)}`,
                { method: 'POST' },
            )
            if (!res.ok) throw new Error('Price check failed')
            const updated = await res.json()
            setItems((prev) => prev.map((it) => (it.id === itemId ? updated : it)))
            showToast('Price check complete!')
        } catch (err) {
            showToast(err.message, 'error')
        }
    }

    const handleViewHistory = async (itemId) => {
        try {
            const res = await fetch(
                `${API_BASE}/api/watchlist/${itemId}/history?user_email=${encodeURIComponent(email)}`,
            )
            if (!res.ok) throw new Error('Failed to load history')
            const data = await res.json()
            setHistoryModal(data)
        } catch (err) {
            showToast(err.message, 'error')
        }
    }

    return (
        <div className="watchlist-page">
            {/* Back button */}
            <button className="watchlist-nav-btn watchlist-nav-btn--back" onClick={onBack}>
                ← Back to Search
            </button>

            <div className="watchlist-page__header">
                <h2 className="watchlist-page__title">🔔 My Watchlist</h2>
                <p className="watchlist-page__subtitle">Track prices and get email alerts when they drop</p>
            </div>

            {/* Email input */}
            {!submitted ? (
                <form className="watchlist-email-form" onSubmit={handleEmailSubmit}>
                    <input
                        type="email"
                        className="watchlist-modal-card__input"
                        placeholder="Enter your email to view watchlist"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                    />
                    <button type="submit" className="watchlist-email-form__btn">View Watchlist</button>
                </form>
            ) : (
                <div className="watchlist-email-bar">
                    <span className="watchlist-email-bar__label">📧 {email}</span>
                    <button
                        className="watchlist-email-bar__change"
                        onClick={() => { setSubmitted(false); setItems([]) }}
                    >
                        Change
                    </button>
                </div>
            )}

            {/* Content */}
            {loading && <WatchlistSkeleton />}

            {error && <div className="watchlist-error">⚠️ {error}</div>}

            {!loading && !error && submitted && items.length === 0 && (
                <div className="empty-watchlist">
                    <div className="empty-watchlist__icon">💤</div>
                    <div className="empty-watchlist__title">No saved items yet</div>
                    <div className="empty-watchlist__text">
                        Search for products and tap the ❤️ button on any offer to save it for price drop alerts.
                    </div>
                </div>
            )}

            {!loading && items.length > 0 && (
                <div className="watchlist-grid">
                    {items.map((item) => (
                        <WatchlistCard
                            key={item.id}
                            item={item}
                            onRemove={handleRemove}
                            onCheckNow={handleCheckNow}
                            onViewHistory={handleViewHistory}
                        />
                    ))}
                </div>
            )}

            {/* Price History Modal */}
            {historyModal && (
                <PriceHistoryModal data={historyModal} onClose={() => setHistoryModal(null)} />
            )}

            {/* Toast */}
            {toast && (
                <div className={`watchlist-toast watchlist-toast--${toast.type}`}>
                    {toast.msg}
                </div>
            )}
        </div>
    )
}
