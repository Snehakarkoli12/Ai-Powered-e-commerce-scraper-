import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'

const API_BASE = ''

/**
 * Heart-icon button → opens full-screen blurred modal to save product to watchlist.
 *
 * Flow:
 *   1. User clicks heart → full-screen overlay w/ blur opens
 *   2. Shows product card, email input, threshold pills
 *   3. On save → backend saves + sends AI-generated confirmation email
 *   4. Success animation + toast
 */
export default function WatchlistButton({ offer, currentQuery, currentMode }) {
    const [open, setOpen] = useState(false)
    const [email, setEmail] = useState(() => localStorage.getItem('wl_email') || '')
    const [threshold, setThreshold] = useState(10)
    const [saving, setSaving] = useState(false)
    const [saved, setSaved] = useState(false)
    const [toast, setToast] = useState(null)
    const [success, setSuccess] = useState(false)   // success animation inside modal

    /* ── Check if already saved ──────────────────────────────────────────── */
    useEffect(() => {
        const storedEmail = localStorage.getItem('wl_email')
        if (!storedEmail) return
        const savedKeys = JSON.parse(localStorage.getItem('wl_saved') || '{}')
        const key = `${storedEmail}::${offer.listing_url || offer.url || ''}`
        if (savedKeys[key]) setSaved(true)
    }, [offer])

    const showToast = (msg, type = 'success') => {
        setToast({ msg, type })
        setTimeout(() => setToast(null), 4000)
    }

    const handleSave = async () => {
        if (!email.trim()) return
        setSaving(true)
        try {
            const res = await fetch(`${API_BASE}/api/watchlist/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_email: email.trim(),
                    product_query: currentQuery,
                    product_title: offer.title || 'Unknown Product',
                    site: offer.platform_name || offer.site || '',
                    saved_price: offer.effective_price || offer.base_price || 0,
                    product_url: offer.listing_url || offer.url || '',
                    thumbnail_url: offer.image_url || null,
                    mode: currentMode || 'balanced',
                    alert_threshold: threshold,
                }),
            })
            if (!res.ok) {
                const err = await res.json().catch(() => ({}))
                throw new Error(err.detail || 'Failed to save')
            }
            localStorage.setItem('wl_email', email.trim())
            const savedKeys = JSON.parse(localStorage.getItem('wl_saved') || '{}')
            savedKeys[`${email.trim()}::${offer.listing_url || offer.url || ''}`] = true
            localStorage.setItem('wl_saved', JSON.stringify(savedKeys))

            // Show success animation inside modal
            setSuccess(true)
            setSaved(true)

            // Close modal after animation, show toast
            setTimeout(() => {
                setOpen(false)
                setSuccess(false)
                showToast(`✅ Added to watchlist! Confirmation email sent to ${email.trim()}`)
            }, 2200)
        } catch (err) {
            showToast(err.message || 'Save failed', 'error')
        } finally {
            setSaving(false)
        }
    }

    const handleUnsave = () => {
        const savedKeys = JSON.parse(localStorage.getItem('wl_saved') || '{}')
        const key = `${email.trim()}::${offer.listing_url || offer.url || ''}`
        delete savedKeys[key]
        localStorage.setItem('wl_saved', JSON.stringify(savedKeys))
        setSaved(false)
        showToast('Removed from local view. Visit Watchlist to fully remove.', 'info')
    }

    const thresholds = [5, 10, 15, 20]
    const productUrl = offer.listing_url || offer.url || ''
    const price = offer.effective_price ?? offer.base_price

    return (
        <>
            {/* Heart button */}
            <button
                className={`watchlist-btn ${saved ? 'watchlist-btn--saved' : ''}`}
                onClick={() => saved ? handleUnsave() : setOpen(true)}
                title={saved ? 'Saved to watchlist' : 'Save for later'}
                type="button"
            >
                {saved ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                        <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
                    </svg>
                ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
                    </svg>
                )}
            </button>

            {/* ── Full-screen blurred overlay + modal (portal to body) ──── */}
            {open && createPortal(
                <div className="wl-overlay" onClick={() => !saving && !success && setOpen(false)}>
                    <div className="wl-modal" onClick={(e) => e.stopPropagation()}>

                        {/* Success state */}
                        {success ? (
                            <div className="wl-modal__success">
                                <div className="wl-modal__success-icon">
                                    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                                        <polyline points="22 4 12 14.01 9 11.01" />
                                    </svg>
                                </div>
                                <h3 className="wl-modal__success-title">Added to Watchlist!</h3>
                                <p className="wl-modal__success-text">
                                    Confirmation email is on its way to<br />
                                    <strong>{email}</strong>
                                </p>
                                <p className="wl-modal__success-sub">
                                    We'll notify you when the price drops by {threshold}% or more.
                                </p>
                            </div>
                        ) : (
                            <>
                                {/* Header */}
                                <div className="wl-modal__header">
                                    <div className="wl-modal__header-icon">
                                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
                                        </svg>
                                    </div>
                                    <div>
                                        <h3 className="wl-modal__title">Save to Watchlist</h3>
                                        <p className="wl-modal__subtitle">Get email alerts when the price drops</p>
                                    </div>
                                    <button className="wl-modal__close" onClick={() => setOpen(false)}>
                                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                                        </svg>
                                    </button>
                                </div>

                                {/* Product Preview Card */}
                                <div className="wl-modal__product">
                                    <div className="wl-modal__product-img-wrap">
                                        {offer.image_url ? (
                                            <img src={offer.image_url} alt="" className="wl-modal__product-img" />
                                        ) : (
                                            <div className="wl-modal__product-img-placeholder">📦</div>
                                        )}
                                    </div>
                                    <div className="wl-modal__product-info">
                                        <div className="wl-modal__product-site">
                                            <span className="wl-modal__product-site-dot" />
                                            {offer.platform_name}
                                        </div>
                                        <div className="wl-modal__product-name">{offer.title}</div>
                                        <div className="wl-modal__product-price-row">
                                            <span className="wl-modal__product-price">
                                                {price != null ? `₹${Number(price).toLocaleString('en-IN')}` : 'N/A'}
                                            </span>
                                            {offer.base_price != null && offer.base_price !== offer.effective_price && (
                                                <span className="wl-modal__product-mrp">
                                                    ₹{Number(offer.base_price).toLocaleString('en-IN')}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* Divider */}
                                <div className="wl-modal__divider" />

                                {/* Email Input */}
                                <div className="wl-modal__field">
                                    <label className="wl-modal__label">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                            <rect x="2" y="4" width="20" height="16" rx="2" />
                                            <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
                                        </svg>
                                        Email for alerts
                                    </label>
                                    <input
                                        type="email"
                                        className="wl-modal__input"
                                        placeholder="your@email.com"
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        autoFocus
                                    />
                                </div>

                                {/* Alert Threshold */}
                                <div className="wl-modal__field">
                                    <label className="wl-modal__label">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                            <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                                            <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
                                        </svg>
                                        Alert when price drops by
                                    </label>
                                    <div className="wl-modal__pills">
                                        {thresholds.map((t) => (
                                            <button
                                                key={t}
                                                className={`wl-pill ${threshold === t ? 'wl-pill--active' : ''}`}
                                                onClick={() => setThreshold(t)}
                                                type="button"
                                            >
                                                <span className="wl-pill__pct">{t}%</span>
                                                <span className="wl-pill__label">
                                                    {price != null ? `Save ₹${Math.round(price * t / 100).toLocaleString('en-IN')}` : 'drop'}
                                                </span>
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                {/* Info Note */}
                                <div className="wl-modal__info">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg>
                                    We check prices every 6 hours across all marketplaces. You'll receive an AI-generated email when this product's price drops.
                                </div>

                                {/* Submit */}
                                <button
                                    className="wl-modal__submit"
                                    onClick={handleSave}
                                    disabled={saving || !email.trim()}
                                >
                                    {saving ? (
                                        <>
                                            <span className="wl-modal__submit-spinner" />
                                            Saving & sending email…
                                        </>
                                    ) : (
                                        <>🔔 Save & Get Email Alerts</>
                                    )}
                                </button>
                            </>
                        )}
                    </div>
                </div>,
                document.body
            )}

            {/* Toast */}
            {toast && createPortal(
                <div className={`watchlist-toast watchlist-toast--${toast.type}`}>
                    {toast.msg}
                </div>,
                document.body
            )}
        </>
    )
}
