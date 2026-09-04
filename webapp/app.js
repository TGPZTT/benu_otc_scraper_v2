const DATA_URL = "../data/exports/grouped_catalog.json";

const INGREDIENT_ALIASES = new Map([
  ["ibuprofen", "ibuprofén"],
  ["cetirizin-dihidroklorid", "cetirizin"],
  ["cetirizin hexal a cetirizin-dihidroklorid", "cetirizin"],
  ["cetirizin hexal cseppek a cetirizin-dihidroklorid", "cetirizin"],
  ["levocetirizin-dihidroklorid", "levocetirizin"],
  ["azelasztin-hidroklorid", "azelasztin"],
  ["benzidamin-hidroklorid", "benzidamin"],
  ["lidokain-hidroklorid", "lidokain"],
  ["fenilefrin-hidroklorid", "fenilefrin"],
]);

const state = {
  groups: [],
  query: "",
  category: "",
  subcategory: "",
  family: "",
  form: "",
  sort: "category",
  onlySavings: false,
  openFamilies: new Set(),
  openGroups: new Set(),
};

const els = {
  datasetMeta: document.querySelector("#datasetMeta"),
  searchInput: document.querySelector("#searchInput"),
  categorySelect: document.querySelector("#categorySelect"),
  sortSelect: document.querySelector("#sortSelect"),
  formSelect: document.querySelector("#formSelect"),
  onlySavings: document.querySelector("#onlySavings"),
  resetButton: document.querySelector("#resetButton"),
  activeFilters: document.querySelector("#activeFilters"),
  categoryList: document.querySelector("#categoryList"),
  ingredientList: document.querySelector("#ingredientList"),
  resultTitle: document.querySelector("#resultTitle"),
  resultMeta: document.querySelector("#resultMeta"),
  insightBox: document.querySelector("#insightBox"),
  groupList: document.querySelector("#groupList"),
  emptyState: document.querySelector("#emptyState"),
  familyTemplate: document.querySelector("#familyTemplate"),
  groupTemplate: document.querySelector("#groupTemplate"),
};

const collator = new Intl.Collator("hu-HU");

function formatHuf(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${Number(value).toLocaleString("hu-HU")} Ft`;
}

function formatUnit(value, unit) {
  if (value === null || value === undefined || value === "") return "-";
  const rounded = Math.round(Number(value) * 10) / 10;
  return `${rounded.toLocaleString("hu-HU")} Ft/${unit || "egység"}`;
}

function foldText(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[‐‑‒–—−]/g, "-")
    .replace(/[•]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("hu-HU");
}

function slugify(value) {
  const slug = foldText(value).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return slug || "unknown";
}

function categoryOf(group) {
  return group.primary_category || "Egyéb";
}

function subcategoryOf(group) {
  const counts = new Map();
  for (const product of group.products || []) {
    const value = product.secondary_category || "Nincs alkategória";
    counts.set(value, (counts.get(value) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || collator.compare(a[0], b[0]))[0]?.[0] || "Nincs alkategória";
}

function displayIngredient(group) {
  const raw = group.ingredient_display || "Ismeretlen hatóanyag";
  const folded = foldText(raw);
  if (INGREDIENT_ALIASES.has(folded)) return INGREDIENT_ALIASES.get(folded);
  if (folded.includes("levocetirizin")) return "levocetirizin";
  if (folded.includes("cetirizin") && folded.includes("dihidroklorid")) return "cetirizin";
  if (folded.includes("azelasztin") && folded.includes("hidroklorid")) return "azelasztin";
  if (folded.startsWith("a fulcsepp fenazon")) return "fenazon + lidokain";
  return raw.replace(/^•\s*/, "");
}

function purposeText(group) {
  const ingredient = foldText(displayIngredient(group));
  const category = foldText(categoryOf(group));
  const sub = foldText(subcategoryOf(group));
  if (category.includes("allergia") || ["cetirizin", "levocetirizin", "loratadin", "dezloratadin", "bilasztin", "azelasztin"].some((name) => ingredient.includes(name))) {
    return "Allergiás orr- és szemtünetekre használt készítmények. A forma sokat számít: tabletta általános tünetekre, szemcsepp/spray helyi panaszra.";
  }
  if (category.includes("fajdalom") || ["ibuprofen", "ibuprofén", "naprox", "diklofen", "paracetamol", "metamizol"].some((name) => ingredient.includes(name))) {
    return "Fájdalom, láz vagy gyulladás kategóriájú készítmények. Az ár-összevetésnél azonos hatóanyag, erősség és forma mellett érdemes dönteni.";
  }
  if (category.includes("megfazas") || sub.includes("orrdugulas") || sub.includes("kohoges")) {
    return "Megfázásos tünetekre sorolt készítmények. Kombinált szereknél különösen figyeld, hogy több hatóanyag is lehet bennük.";
  }
  if (category.includes("belflora") || category.includes("emesztes")) {
    return "Emésztési panaszok, savtúltengés, puffadás vagy bélflóra kategóriába sorolt készítmények.";
  }
  if (category.includes("borgyogyaszat") || category.includes("intim")) {
    return "Helyi alkalmazású bőrgyógyászati vagy intim készítmény. Itt a forma és a kiszerelés gyakran fontosabb, mint a darabár.";
  }
  if (category.includes("sziv") || category.includes("errendszer")) {
    return "Érrendszeri vagy keringéssel kapcsolatos OTC kategória. Az azonos hatóanyagú termékeket érdemes egységár szerint nézni.";
  }
  return "A rövid leírás a BENU-kategória és a termékadatok alapján készült; nem terápiás ajánlás.";
}

function groupSearchText(group) {
  const productText = (group.products || [])
    .map((product) => [
      product.name,
      product.brand,
      product.primary_category,
      product.secondary_category,
      product.active_ingredient_raw,
    ].join(" "))
    .join(" ");
  const text = [
    displayIngredient(group),
    group.ingredient_display,
    group.strength_display,
    group.form,
    categoryOf(group),
    subcategoryOf(group),
    purposeText(group),
    productText,
  ].join(" ");
  return foldText(text);
}

function baseFilteredGroups({ includeFamily = false } = {}) {
  const query = foldText(state.query);
  let groups = state.groups;
  if (state.category) groups = groups.filter((group) => categoryOf(group) === state.category);
  if (state.subcategory) groups = groups.filter((group) => subcategoryOf(group) === state.subcategory);
  if (state.form) groups = groups.filter((group) => (group.form || "Ismeretlen forma") === state.form);
  if (!includeFamily && state.family) groups = groups.filter((group) => displayIngredient(group) === state.family);
  if (state.onlySavings) groups = groups.filter((group) => group.product_count > 1 && group.savings_vs_max_unit_pct);
  if (query) groups = groups.filter((group) => groupSearchText(group).includes(query));
  return groups;
}

function filteredGroups() {
  return baseFilteredGroups();
}

function countBy(items, fn) {
  const counts = new Map();
  for (const item of items) {
    const key = fn(item);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}

function topEntry(counts) {
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || collator.compare(a[0], b[0]))[0]?.[0];
}

function buildFamilies(groups) {
  const buckets = new Map();
  for (const group of groups) {
    const title = displayIngredient(group);
    const key = slugify(title);
    if (!buckets.has(key)) buckets.set(key, { key, title, groups: [], productCount: 0 });
    const family = buckets.get(key);
    family.groups.push(group);
    family.productCount += group.product_count || 0;
  }

  const families = [...buckets.values()].map((family) => {
    const unitValues = family.groups.map((group) => group.min_unit_price_huf).filter((value) => value !== null && value !== undefined);
    const priceValues = family.groups.flatMap((group) => [group.min_price_huf, group.max_price_huf]).filter((value) => value !== null && value !== undefined);
    const savings = family.groups.map((group) => group.savings_vs_max_unit_pct || 0);
    const categories = countBy(family.groups, categoryOf);
    const forms = countBy(family.groups, (group) => group.form || "Ismeretlen forma");
    family.minUnit = unitValues.length ? Math.min(...unitValues) : null;
    family.maxUnit = unitValues.length ? Math.max(...unitValues) : null;
    family.minPrice = priceValues.length ? Math.min(...priceValues) : null;
    family.maxPrice = priceValues.length ? Math.max(...priceValues) : null;
    family.maxSavings = savings.length ? Math.max(...savings) : 0;
    family.primaryCategory = topEntry(categories) || "Egyéb";
    family.forms = [...forms.keys()].sort((a, b) => collator.compare(a, b));
    family.groups.sort(groupSort);
    return family;
  });

  families.sort(familySort);
  return families;
}

function groupSort(a, b) {
  return collator.compare(a.strength_display || "", b.strength_display || "")
    || collator.compare(a.form || "", b.form || "")
    || (a.min_unit_price_huf ?? Infinity) - (b.min_unit_price_huf ?? Infinity);
}

function familySort(a, b) {
  if (state.sort === "savings") {
    return (b.maxSavings || 0) - (a.maxSavings || 0)
      || b.productCount - a.productCount
      || collator.compare(a.title, b.title);
  }
  if (state.sort === "unit") {
    return (a.minUnit ?? Infinity) - (b.minUnit ?? Infinity)
      || collator.compare(a.title, b.title);
  }
  if (state.sort === "count") {
    return b.productCount - a.productCount
      || collator.compare(a.title, b.title);
  }
  if (state.sort === "name" || state.sort === "family") {
    return collator.compare(a.title, b.title);
  }
  return collator.compare(a.primaryCategory, b.primaryCategory)
    || collator.compare(a.title, b.title);
}

function buildCategoryTree() {
  const tree = new Map();
  for (const group of state.groups) {
    const category = categoryOf(group);
    const subcategory = subcategoryOf(group);
    if (!tree.has(category)) tree.set(category, { total: 0, subs: new Map() });
    const entry = tree.get(category);
    entry.total += 1;
    entry.subs.set(subcategory, (entry.subs.get(subcategory) || 0) + 1);
  }
  return [...tree.entries()].sort((a, b) => collator.compare(a[0], b[0]));
}

function buildFormOptions() {
  return [...countBy(state.groups, (group) => group.form || "Ismeretlen forma").keys()]
    .sort((a, b) => collator.compare(a, b));
}

function buildIngredientOptions() {
  const groups = baseFilteredGroups({ includeFamily: true });
  const counts = countBy(groups, displayIngredient);
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || collator.compare(a[0], b[0]))
    .slice(0, 42);
}

function renderFilters() {
  renderActiveFilters();
  renderCategories();
  renderIngredientList();
  renderFormSelect();
}

function renderActiveFilters() {
  els.activeFilters.innerHTML = "";
  const filters = [
    ["Keresés", state.query, () => { state.query = ""; els.searchInput.value = ""; }],
    ["Kategória", state.category, () => { state.category = ""; state.subcategory = ""; }],
    ["Alkategória", state.subcategory, () => { state.subcategory = ""; }],
    ["Hatóanyag", state.family, () => { state.family = ""; }],
    ["Forma", state.form, () => { state.form = ""; }],
    ["Árkülönbség", state.onlySavings ? "van olcsóbb" : "", () => { state.onlySavings = false; els.onlySavings.checked = false; }],
  ].filter(([, value]) => value);
  for (const [label, value, clear] of filters) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "filter-chip";
    chip.innerHTML = `<span>${escapeHtml(label)}: ${escapeHtml(value)}</span><strong>×</strong>`;
    chip.addEventListener("click", () => {
      clear();
      syncControls();
      render();
    });
    els.activeFilters.append(chip);
  }
}

function renderCategories() {
  const total = state.groups.length;
  els.categoryList.innerHTML = "";
  els.categoryList.append(categoryButton("Összes", total, "", ""));

  els.categorySelect.innerHTML = '<option value="">Minden kategória</option>';
  for (const [category, entry] of buildCategoryTree()) {
    const details = document.createElement("div");
    details.className = `category-section${state.category === category ? " open" : ""}`;
    details.append(categoryButton(category, entry.total, category, ""));
    const subs = document.createElement("div");
    subs.className = "subcategory-list";
    subs.hidden = state.category !== category;
    for (const [subcategory, count] of [...entry.subs.entries()].sort((a, b) => collator.compare(a[0], b[0]))) {
      subs.append(categoryButton(subcategory, count, category, subcategory));
    }
    details.append(subs);
    els.categoryList.append(details);

    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    els.categorySelect.append(option);
  }
  els.categorySelect.value = state.category;
}

function categoryButton(label, count, category, subcategory) {
  const button = document.createElement("button");
  button.type = "button";
  const active = state.category === category && state.subcategory === subcategory;
  button.className = `category-link${active ? " active" : ""}`;
  button.innerHTML = `<span>${escapeHtml(label)}</span><span>${count.toLocaleString("hu-HU")}</span>`;
  button.addEventListener("click", (event) => {
    event.preventDefault();
    state.category = category;
    state.subcategory = subcategory;
    syncControls();
    render();
  });
  return button;
}

function renderIngredientList() {
  els.ingredientList.innerHTML = "";
  for (const [ingredient, count] of buildIngredientOptions()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `ingredient-link${state.family === ingredient ? " active" : ""}`;
    button.innerHTML = `<span>${escapeHtml(ingredient)}</span><span>${count.toLocaleString("hu-HU")}</span>`;
    button.addEventListener("click", () => {
      state.family = state.family === ingredient ? "" : ingredient;
      render();
    });
    els.ingredientList.append(button);
  }
}

function renderFormSelect() {
  const previous = state.form;
  const forms = buildFormOptions();
  els.formSelect.innerHTML = '<option value="">Minden forma</option>';
  for (const form of forms) {
    const option = document.createElement("option");
    option.value = form;
    option.textContent = form;
    els.formSelect.append(option);
  }
  state.form = forms.includes(previous) ? previous : "";
  els.formSelect.value = state.form;
}

function currentInsight(families, groups) {
  if (!groups.length) return "";
  if (state.family && families[0]) return purposeText(families[0].groups[0]);
  if (state.category || state.subcategory) {
    const comparable = groups.filter((group) => group.product_count > 1 && group.savings_vs_max_unit_pct);
    if (!comparable.length) return "Ebben a szűrésben kevés többtermékes összehasonlító csoport van, ezért inkább forma és kiszerelés szerint érdemes nézni.";
    const best = [...comparable].sort((a, b) => (b.savings_vs_max_unit_pct || 0) - (a.savings_vs_max_unit_pct || 0))[0];
    return `Legnagyobb látható egységár-különbség: ${displayIngredient(best)}, ${best.strength_display || "erősség nélkül"} / ${best.form || "forma nélkül"} (${Math.round(best.savings_vs_max_unit_pct)}%).`;
  }
  return "Nyiss ki egy hatóanyagcsaládot, azon belül válaszd az azonos erősség/formát, és ott hasonlítsd az egységárat.";
}

function render() {
  const groups = filteredGroups();
  const families = buildFamilies(groups);
  const productCount = groups.reduce((sum, group) => sum + group.product_count, 0);

  els.resultTitle.textContent = state.family || state.subcategory || state.category || "Összes OTC csoport";
  els.resultMeta.textContent = `${families.length.toLocaleString("hu-HU")} hatóanyagcsalád, ${groups.length.toLocaleString("hu-HU")} erősség/forma csoport, ${productCount.toLocaleString("hu-HU")} készítmény`;
  els.insightBox.textContent = currentInsight(families, groups);

  els.groupList.innerHTML = "";
  els.emptyState.hidden = families.length > 0;
  for (const family of families) {
    els.groupList.append(renderFamily(family));
  }
  renderFilters();
}

function renderFamily(family) {
  const node = els.familyTemplate.content.firstElementChild.cloneNode(true);
  const summary = node.querySelector(".family-summary");
  const detail = node.querySelector(".family-detail");
  const isOpen = state.openFamilies.has(family.key);
  node.classList.toggle("open", isOpen);
  detail.hidden = !isOpen;

  node.querySelector(".family-title").textContent = family.title;
  node.querySelector(".family-subtitle").textContent = [
    `${family.groups.length} erősség/forma`,
    `${family.productCount} készítmény`,
    family.forms.slice(0, 3).join(", "),
  ].filter(Boolean).join(" / ");
  node.querySelector(".family-purpose").textContent = purposeText(family.groups[0]);

  const minPrice = formatHuf(family.minPrice);
  const maxPrice = formatHuf(family.maxPrice);
  node.querySelector(".family-price-range").textContent = minPrice === maxPrice ? minPrice : `${minPrice} - ${maxPrice}`;

  const unit = family.groups.find((group) => group.comparison_unit)?.comparison_unit;
  const minUnit = formatUnit(family.minUnit, unit);
  const maxUnit = formatUnit(family.maxUnit, unit);
  node.querySelector(".family-unit-range").textContent = minUnit === maxUnit ? minUnit : `${minUnit} - ${maxUnit}`;

  const badge = node.querySelector(".family-saving");
  if (family.maxSavings) {
    badge.textContent = `-${Math.round(family.maxSavings)}%`;
  } else {
    badge.textContent = family.productCount === 1 ? "egyedül" : "nincs adat";
    badge.classList.add("single");
  }

  for (const group of family.groups) {
    detail.append(renderGroup(group));
  }

  summary.addEventListener("click", () => {
    if (state.openFamilies.has(family.key)) state.openFamilies.delete(family.key);
    else state.openFamilies.add(family.key);
    render();
  });
  return node;
}

function renderGroup(group) {
  const node = els.groupTemplate.content.firstElementChild.cloneNode(true);
  const summary = node.querySelector(".group-summary");
  const detail = node.querySelector(".group-detail");
  const key = group.comparison_group_key;
  const isOpen = state.openGroups.has(key);
  node.classList.toggle("open", isOpen);
  detail.hidden = !isOpen;

  node.querySelector(".group-title").textContent = [
    group.strength_display || "Erősség nélkül",
    group.form || "Forma nélkül",
  ].join(" · ");
  node.querySelector(".group-subtitle").textContent = [
    subcategoryOf(group),
    `${group.product_count} készítmény`,
  ].filter(Boolean).join(" / ");

  const minPrice = formatHuf(group.min_price_huf);
  const maxPrice = formatHuf(group.max_price_huf);
  node.querySelector(".price-range").textContent = minPrice === maxPrice ? minPrice : `${minPrice} - ${maxPrice}`;

  const minUnit = formatUnit(group.min_unit_price_huf, group.comparison_unit);
  const maxUnit = formatUnit(group.max_unit_price_huf, group.comparison_unit);
  node.querySelector(".unit-range").textContent = minUnit === maxUnit ? minUnit : `${minUnit} - ${maxUnit}`;

  const badge = node.querySelector(".saving-badge");
  if (group.savings_vs_max_unit_pct) {
    badge.textContent = `-${Math.round(group.savings_vs_max_unit_pct)}%`;
  } else {
    badge.textContent = group.product_count === 1 ? "egyedül" : "nincs adat";
    badge.classList.add("single");
  }

  node.querySelector(".detail-note").textContent = group.product_count > 1
    ? `Azonosított legkedvezőbb egységár: ${group.cheapest_product_name}.`
    : "Ebben az erősség/forma csoportban egy termék van az aktuális BENU-listában.";

  const tbody = node.querySelector("tbody");
  for (const product of group.products || []) {
    tbody.append(renderProductRow(product, group.cheapest_product_id));
  }

  summary.addEventListener("click", () => {
    if (state.openGroups.has(key)) state.openGroups.delete(key);
    else state.openGroups.add(key);
    render();
  });
  return node;
}

function renderProductRow(product, cheapestId) {
  const row = document.createElement("tr");
  row.className = product.id === cheapestId ? "best" : "";
  const hasMissingEan = (product.quality_flags || []).includes("missing_ean");
  row.innerHTML = `
    <td>
      <a class="product-name" href="${escapeHtml(product.url)}" target="_blank" rel="noreferrer">${escapeHtml(product.name)}</a>
      ${product.id === cheapestId ? '<span class="tag">legolcsóbb</span>' : ""}
      ${hasMissingEan ? '<span class="tag warn">EAN hiány</span>' : ""}
    </td>
    <td>${escapeHtml(product.package_label || "-")}</td>
    <td><strong>${formatHuf(product.price_huf)}</strong></td>
    <td>${formatUnit(product.unit_price_huf, product.unit_price_unit || product.comparison_unit)}</td>
  `;
  return row;
}

function syncControls() {
  els.searchInput.value = state.query;
  els.categorySelect.value = state.category;
  els.sortSelect.value = state.sort;
  els.formSelect.value = state.form;
  els.onlySavings.checked = state.onlySavings;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function bindEvents() {
  els.searchInput.addEventListener("input", (event) => {
    state.query = event.target.value;
    render();
  });
  els.categorySelect.addEventListener("change", (event) => {
    state.category = event.target.value;
    state.subcategory = "";
    render();
  });
  els.sortSelect.addEventListener("change", (event) => {
    state.sort = event.target.value;
    render();
  });
  els.formSelect.addEventListener("change", (event) => {
    state.form = event.target.value;
    render();
  });
  els.onlySavings.addEventListener("change", (event) => {
    state.onlySavings = event.target.checked;
    render();
  });
  els.resetButton.addEventListener("click", () => {
    state.query = "";
    state.category = "";
    state.subcategory = "";
    state.family = "";
    state.form = "";
    state.sort = "category";
    state.onlySavings = false;
    state.openFamilies.clear();
    state.openGroups.clear();
    syncControls();
    render();
  });
}

async function init() {
  bindEvents();
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.groups = data.groups || [];
    els.datasetMeta.textContent = `${data.counts.otc_products} OTC gyógyszer / ${data.counts.comparison_groups} összehasonlító csoport / ${data.counts.multi_product_groups} többtermékes csoport`;
    render();
  } catch (error) {
    els.datasetMeta.textContent = "Nem sikerült betölteni a katalógust.";
    els.resultTitle.textContent = "Adatbetöltési hiba";
    els.resultMeta.textContent = "Indíts helyi szervert a projekt gyökeréből: python -m http.server 8000";
    els.emptyState.hidden = false;
    els.emptyState.textContent = String(error.message || error);
  }
}

init();
