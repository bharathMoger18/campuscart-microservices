import { api } from './core/api.js';
import { STRIPE_PUBLISHABLE_KEY } from './core/config.js';
import { showAlert } from './core/utils.js';

const checkoutSummary =
  document.getElementById(
    'checkoutSummary'
  );

const placeOrderBtn =
  document.getElementById(
    'placeOrderBtn'
  );

let cartData = null;
let stripeInstance = null;
let cardElement = null;

function initStripe() {
  if (!window.Stripe || stripeInstance) return;
  stripeInstance = window.Stripe(STRIPE_PUBLISHABLE_KEY);
  const elements = stripeInstance.elements();
  cardElement = elements.create('card', {
    style: {
      base: {
        color: '#e2e2e8',
        fontFamily: 'DM Sans, sans-serif',
        fontSize: '15px',
        '::placeholder': { color: '#6b7280' },
      }
    }
  });
  cardElement.mount('#card-element');
  cardElement.on('change', (ev) => {
    const el = document.getElementById('card-errors');
    if (el) el.textContent = ev.error ? ev.error.message : '';
  });
}

document.addEventListener(
  'DOMContentLoaded',
  () => {
    loadCheckoutSummary();

    placeOrderBtn
      ?.addEventListener(
        'click',
        placeOrder
      );

    // Show/hide Stripe card element based on payment selection
    document.querySelectorAll('input[name=payment]').forEach(radio => {
      radio.addEventListener('change', () => {
        const wrapper = document.getElementById('stripe-card-wrapper');
        if (!wrapper) return;
        if (radio.value === 'card') {
          wrapper.style.display = 'block';
          // Small delay to ensure DOM is visible before mounting
          // initStripe disabled - using Stripe redirect flow;
        } else {
          wrapper.style.display = 'none';
        }
      });
    });

    const urlParams =
      new URLSearchParams(
        window.location.search
      );

    if (
      urlParams.get('cancel') ===
      'true'
    ) {
      showAlert(
        'Payment cancelled. You can try again.',
        'error'
      );
    }
  }
);

async function loadCheckoutSummary() {
  try {
    const cart =
      await api.get('/cart/');

    cartData = cart;

    if (!cart.items?.length) {
      checkoutSummary.innerHTML = `
        <div class="empty">
          Your cart is empty.
        </div>
      `;

      if (placeOrderBtn) {
        placeOrderBtn.disabled = true;
      }

      return;
    }

    const itemsHtml =
      cart.items.map(it => `
        <div class="checkout-item">
          <img
            src="${
              (it.product_detail || it.product || {}).image ||
              '/assets/images/placeholder.png'
            }"

            alt="${
              escapeHtml(
                (it.product_detail || it.product || {}).title
              )
            }"
          />

          <div class="checkout-item-info">
            <strong>
              ${
                escapeHtml(
                  (it.product_detail || it.product || {}).title
                )
              }
            </strong>

            <span>
              Qty: ${it.quantity}
            </span>
          </div>

          <div class="checkout-item-price">
            &#8377;${it.total_price}
          </div>
        </div>
      `).join('');

    checkoutSummary.innerHTML = `
      ${itemsHtml}

      <div class="checkout-total-row">
        <span>
          Total
          (${cart.total_items} items)
        </span>

        <span>
          &#8377;${cart.total_price}
        </span>
      </div>
    `;
  }
  catch {
    checkoutSummary.innerHTML = `
      <div class="empty">
        Unable to load summary.
      </div>
    `;
  }
}

async function placeOrder() {
  const address =
    document
      .getElementById('address')
      .value
      .trim();

  const payment =
    document.querySelector(
      'input[name=payment]:checked'
    )?.value || 'cod';

  if (!address) {
    showAlert(
      'Please enter your shipping address.',
      'error'
    );

    return;
  }

  placeOrderBtn.disabled = true;

  placeOrderBtn.textContent =
    'Processing...';

  // Save total before
  // cart gets cleared
  const totalPrice =
    parseFloat(
      cartData?.total_price || 0
    );

  try {
    // API returns LIST of orders
    // (one per seller)
    const orders =
      await api.post(
        '/orders/create/',
        {
          address,
          payment_method: payment.toUpperCase(),
        }
      );

    // Get first order ID
    const orderList =
      Array.isArray(orders)
        ? orders
        : [orders];

    const firstOrder =
      orderList[0];

    const orderId =
      firstOrder?.id;

    if (payment === 'card') {
      if (!stripeInstance || !cardElement) {
        showAlert('Please enter your card details.', 'error');
        placeOrderBtn.disabled = false;
        placeOrderBtn.textContent = 'Place Order →';
        return;
      }

      placeOrderBtn.textContent = 'Redirecting to Stripe...';

      const sessionRes = await api.post('/payments/create-checkout-session/', { order_id: orderId });

      if (sessionRes?.url) {
        window.location.href = sessionRes.url;
      } else {
        showAlert('Failed to initiate payment.', 'error');
        placeOrderBtn.disabled = false;
        placeOrderBtn.textContent = 'Place Order →';
      }
    }
    else {
      showAlert(
        'Order placed successfully!',
        'success'
      );

      setTimeout(
        () => (
          window.location.href =
            '/orders/my_orders.html'
        ),
        1000
      );
    }
  }
  catch (err) {
    showAlert(
      err?.data?.detail ||
      'Failed to place order.',
      'error'
    );

    placeOrderBtn.disabled = false;

    placeOrderBtn.textContent =
      'Place Order →';
  }
}

function escapeHtml(s) {
  if (!s) return '';

  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#039;');
}
