/**
 * Security utility functions for x402chat
 * Prevents XSS by escaping user-controlled content
 */

/**
 * Escapes HTML special characters to prevent XSS
 * @param {string} str - The string to escape
 * @returns {string} - HTML-safe string
 */
export function escapeHtml(str) {
  if (str == null || str === '') return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

/**
 * Escapes HTML attribute values
 * @param {string} str - The string to escape
 * @returns {string} - Attribute-safe string
 */
export function escapeAttr(str) {
  if (str == null || str === '') return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
