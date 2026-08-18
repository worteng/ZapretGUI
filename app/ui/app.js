"use strict";

/* =========================================================
 * DOM
 * ========================================================= */

const $ = (selector) => document.querySelector(selector);


/* =========================================================
 * STATUS
 * ========================================================= */

const STATUS = {
  active: {
    word: "Работает",
    cls: "active",
    hint: ""
  },

  inactive: {
    word: "Выключено",
    cls: "inactive",
    hint: "Защита выключена"
  },

  degraded: {
    word: "Проблема",
    cls: "degraded",
    hint: "Часть проверок не работает"
  },

  error: {
    word: "Ошибка",
    cls: "error",
    hint: ""
  }
};


/* =========================================================
 * STATE
 * ========================================================= */

const state = {
  status: "inactive",

  strategyId: "auto",
  strategyName: "Автоматическая",
  strategies: [],

  zapretFound: false,

  busy: false,

  backendReady: false,
  demoMode: false
};

let checking = false;
let refreshTimer = null;
let appInitialized = false;


/* =========================================================
 * PYWEBVIEW API
 * ========================================================= */

function api() {
  if (
    window.pywebview &&
    window.pywebview.api
  ) {
    return window.pywebview.api;
  }

  return null;
}


async function call(method, ...args) {
  const bridge = api();

  if (
    !bridge ||
    typeof bridge[method] !== "function"
  ) {
    throw new Error("Backend недоступен");
  }

  return await bridge[method](...args);
}


/* =========================================================
 * ERROR REPORTING
 * ========================================================= */

window.addEventListener("error", (event) => {
  try {
    const bridge = api();

    if (bridge && typeof bridge.log === "function") {
      bridge.log(
        `error: ${event.message} @ ` +
        `${event.filename || ""}:` +
        `${event.lineno || ""}:` +
        `${event.colno || ""}`
      );
    }
  } catch (_) {}
});


window.addEventListener(
  "unhandledrejection",
  (event) => {
    try {
      const bridge = api();

      if (
        bridge &&
        typeof bridge.log === "function"
      ) {
        bridge.log(
          `rejection: ${event.reason}`
        );
      }
    } catch (_) {}
  }
);


/* =========================================================
 * STORAGE
 * ========================================================= */

/*
 * localStorage отсутствует в некоторых окружениях
 * WebKit/pywebview.
 *
 * Поэтому используем безопасную обёртку.
 */

const store = (() => {
  const memory = new Map();

  let storageAvailable = false;

  try {
    if (
      typeof localStorage !==
      "undefined"
    ) {
      const testKey =
      "__zapretgui_storage_test__";

      localStorage.setItem(
        testKey,
        "1"
      );

      localStorage.removeItem(
        testKey
      );

      storageAvailable = true;
    }
  } catch (_) {
    storageAvailable = false;
  }


  return {
    get(key) {
      if (storageAvailable) {
        try {
          return localStorage.getItem(
            key
          );
        } catch (_) {}
      }

      return memory.has(key)
      ? memory.get(key)
      : null;
    },


    set(key, value) {
      value = String(value);

      if (storageAvailable) {
        try {
          localStorage.setItem(
            key,
            value
          );

          return;
        } catch (_) {}
      }

      memory.set(
        key,
        value
      );
    }
  };
})();


/* =========================================================
 * THEME
 * ========================================================= */

const systemDark =
window.matchMedia
? window.matchMedia(
  "(prefers-color-scheme: dark)"
)
: null;


function applyTheme() {
  const choice =
  store.get("theme") ||
  "auto";

const dark =
choice === "dark" ||
(
  choice === "auto" &&
  systemDark &&
  systemDark.matches
);

document.documentElement.dataset.theme =
dark
? "dark"
: "light";
}


function initTheme() {
  applyTheme();

  if (!systemDark) {
    return;
  }

  const handler = () => {
    if (
      (store.get("theme") ||
      "auto") ===
      "auto"
    ) {
      applyTheme();
    }
  };

  if (
    typeof systemDark.addEventListener ===
    "function"
  ) {
    systemDark.addEventListener(
      "change",
      handler
    );
  } else if (
    typeof systemDark.addListener ===
    "function"
  ) {
    systemDark.addListener(
      handler
    );
  }
}


/* =========================================================
 * ROUTING
 * ========================================================= */

const ROUTES = [
  "home",
"strategies",
"monitoring",
"autopilot",
"diagnostics",
"logs",
"settings"
];


function route() {
  return (
    location.hash
    .replace(/^#\//, "")
    .split("?")[0] ||
    "home"
  );
}


function navigate(name) {
  if (
    !ROUTES.includes(name)
  ) {
    name = "home";
  }

  location.hash =
  "#/" + name;
}


function renderRoute() {
  const current =
  route();

  ROUTES.forEach((name) => {
    const screen =
    $(`#screen-${name}`);

    if (screen) {
      screen.hidden =
      name !== current;
    }

    const item =
    document.querySelector(
      `.dock-item[data-route="${name}"]`
    );

    if (item) {
      item.classList.toggle(
        "active",
        name === current
      );
    }
  });


  if (
    current ===
    "monitoring"
  ) {
    renderMonitoring();
  }
}


/* =========================================================
 * STATUS
 * ========================================================= */

function setStatus(
  status,
  options = {}
) {
  const busy =
  options.busy === true;

  const info =
  STATUS[status] ||
  STATUS.inactive;

  state.status =
  status;


  const dot =
  $("#status-dot");

  if (dot) {
    dot.className =
    "status-dot" +
    (
      busy
      ? " loading"
      : " " + info.cls
    );
  }


  const word =
  $("#status-word");

  if (word) {
    word.textContent =
    info.word;
  }


  const hint =
  $("#status-hint");

  if (hint) {
    hint.textContent =
    info.hint || "";
  }
}


/* =========================================================
 * BUSY
 * ========================================================= */

function setBusy(
  busy,
  label = ""
) {
  state.busy =
  busy;

  const button =
  $("#power-btn");

  if (button) {
    button.disabled =
    busy;

    button.classList.toggle(
      "loading",
      busy
    );
  }


  const powerLabel =
  $("#power-label");

  if (!powerLabel) {
    return;
  }

  if (busy) {
    powerLabel.textContent =
    label;
  } else {
    powerLabel.textContent =
    state.status === "inactive"
    ? "Включить"
    : "Выключить";
  }
}


/* =========================================================
 * POWER
 * ========================================================= */

function renderPower() {
  const button =
  $("#power-btn");

  const label =
  $("#power-label");

  if (!button || !label) {
    return;
  }


  if (state.demoMode) {
    button.classList.toggle(
      "off",
      state.status ===
      "inactive"
    );

    label.textContent =
    state.status === "inactive"
    ? "Включить"
    : "Выключить";

    return;
  }


  if (state.zapretFound) {
    button.classList.toggle(
      "off",
      state.status ===
      "inactive"
    );

    label.textContent =
    state.status === "inactive"
    ? "Включить"
    : "Выключить";
  } else {
    button.classList.add(
      "off"
    );

    label.textContent =
    "Установить zapret2";
  }
}


function renderSteps(
  show,
  steps = []
) {
  const box =
  $("#power-steps");

  if (!box) {
    return;
  }


  if (!show) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }


  box.hidden = false;

  box.innerHTML =
  steps
  .map((step) => {
    const mark =
    step.state === "ok"
    ? "✓"
    : step.state === "err"
    ? "✗"
    : "…";

    return `
    <div class="step ${step.state}">
    <span class="mark">${mark}</span>
    <span>${escapeHtml(step.text)}</span>
    </div>
    `;
  })
  .join("");
}


/* =========================================================
 * POWER ACTION
 * ========================================================= */

async function onPower() {
  if (state.busy) {
    return;
  }


  /*
   * В браузере backend отсутствует.
   * Делаем небольшую UI-демонстрацию.
   */

  if (state.demoMode) {
    const turningOn =
    state.status ===
    "inactive";

  setBusy(
    true,
    turningOn
    ? "Включаю…"
    : "Выключаю…"
  );

  const steps =
  turningOn
  ? [
    {
      text: "Применяю стратегию…",
      state: "wait"
    },
    {
      text: "Запускаю службу…",
      state: "wait"
    },
    {
      text: "Проверяю соединение…",
      state: "wait"
    }
  ]
  : [
    {
      text: "Останавливаю службу…",
      state: "wait"
    }
  ];

  renderSteps(
    true,
    steps
  );


  await delay(700);

  renderSteps(
    true,
    steps.map((step) => ({
      ...step,
      state: "ok"
    }))
  );


  state.status =
  turningOn
  ? "active"
  : "inactive";

  setStatus(
    state.status
  );

  renderPower();

  setBusy(
    false
  );

  toast(
    turningOn
    ? "Защита включена"
    : "Защита выключена"
  );


  setTimeout(
    () => renderSteps(false),
             1200
  );

  return;
  }


  if (!state.zapretFound) {
    toast(
      "Установка zapret2 появится в следующей версии."
    );

    return;
  }


  const turningOn =
  state.status ===
  "inactive";


    setBusy(
      true,
      turningOn
      ? "Проверка…"
      : "Останавливаю…"
    );


    const steps =
    turningOn
    ? [
      {
        text: "Применяю стратегию…",
        state: "wait"
      },
      {
        text: "Запускаю службу…",
        state: "wait"
      },
      {
        text: "Проверяю соединение…",
        state: "wait"
      }
    ]
    : [
      {
        text: "Останавливаю службу…",
        state: "wait"
      }
    ];


    renderSteps(
      true,
      steps
    );


    try {
      const result =
      await call(
        "set_enabled",
        turningOn
      );


      if (
        result &&
        result.ok
      ) {
        renderSteps(
          true,
          steps.map(
            (step) => ({
              ...step,
              state: "ok"
            })
          )
        );
        state.status = turningOn ? "active" : "inactive";
        setStatus(state.status);
        renderPower();

        await refreshState();

        toast(
          result.message ||
          (
            turningOn
            ? "Защита включена"
            : "Защита выключена"
          )
        );

        setTimeout(
          () => renderSteps(false),
                   2000
        );

      } else {
        renderSteps(
          true,
          steps.map(
            (step) => ({
              ...step,
              state: "err"
            })
          )
        );


        toast(
          (
            result &&
            result.message
          ) ||
          (
            result &&
            result.error
          ) ||
          "Не удалось выполнить операцию",
          true
        );
      }

    } catch (error) {
      renderSteps(
        true,
        steps.map(
          (step) => ({
            ...step,
            state: "err"
          })
        )
      );


      toast(
        "Ошибка: " +
        error.message,
        true
      );
    } finally {
      setBusy(false);
      setTimeout(
        () => renderSteps(false),
                 2000
      );
    }
}


/* =========================================================
 * STRATEGIES
 * ========================================================= */

function renderStrategies() {
  const list =
  $("#strategy-list");

  if (!list) {
    return;
  }


  if (
    !state.strategies ||
    !state.strategies.length
  ) {
    list.innerHTML = `
    <div class="card placeholder">
    <p class="muted">
    Стратегии пока не загружены.
    </p>
    </div>
    `;

    return;
  }


  list.innerHTML =
  state.strategies
  .map((strategy) => {
    const active =
    strategy.id ===
    state.strategyId;

    return `
    <div
    class="strategy-row ${
      active
      ? "active"
      : ""
    }"
    data-id="${escapeHtml(
      strategy.id
    )}"
    tabindex="0"
    role="radio"
    aria-checked="${active}"
    >

    <span class="strategy-radio"></span>

    <span class="strategy-row-text">

    <span class="strategy-row-name">
    ${escapeHtml(
      strategy.name ||
      strategy.id ||
      "Без названия"
    )}
    </span>

    <span class="strategy-row-desc">
    ${escapeHtml(
      strategy.description ||
      ""
    )}
    </span>

    </span>

    ${
      active
      ? '<span class="badge">Активна</span>'
      : ""
    }

    <button
      class="strategy-edit"
      type="button"
      data-edit="${escapeHtml(
        strategy.id
      )}"
      aria-label="Изменить стратегию «${escapeHtml(
        strategy.name ||
        strategy.id ||
        "Без названия"
      )}»"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/>
        <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1.11 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1Z"/>
      </svg>
    </button>

    </div>
    `;
  })
  .join("");


  list
  .querySelectorAll(
    ".strategy-row"
  )
  .forEach((row) => {

    const activate =
    () => {
      askApply(
        row.dataset.id
      );
    };


    row.addEventListener(
      "click",
      activate
    );


    row.addEventListener(
      "keydown",
      (event) => {
        if (
          event.key === "Enter" ||
          event.key === " "
        ) {
          event.preventDefault();

          activate();
        }
      }
    );


    const editButton =
    row.querySelector(
      ".strategy-edit"
    );

    if (editButton) {
      editButton.addEventListener(
        "click",
        (event) => {
          event.stopPropagation();

          openEditor(
            editButton.dataset.edit
          );
        }
      );


      editButton.addEventListener(
        "keydown",
        (event) => {
          if (
            event.key === "Enter" ||
            event.key === " "
          ) {
            event.preventDefault();

            event.stopPropagation();

            openEditor(
              editButton.dataset.edit
            );
          }
        }
      );
    }
  });
}


/* =========================================================
 * APPLY STRATEGY
 * ========================================================= */

function askApply(id) {
  const strategy =
  state.strategies.find(
    (item) =>
    String(item.id) ===
    String(id)
  );


  if (!strategy) {
    return;
  }


  if (
    String(id) ===
    String(state.strategyId)
  ) {
    toast(
      "Эта стратегия уже активна"
    );

    return;
  }


  const overlay =
  $("#dialog-overlay");

  const title =
  $("#dialog-title");

  const text =
  $("#dialog-text");

  const ok =
  $("#dialog-ok");


  if (
    !overlay ||
    !title ||
    !text ||
    !ok
  ) {
    return;
  }


  const active =
  state.status ===
  "active";


  title.textContent =
  `Применить стратегию «${strategy.name}»?`;


  text.textContent =
  active
  ? "Защита перезапустится на 1–2 секунды."
  : "Стратегия будет сохранена и применится при включении защиты.";


  ok.textContent =
  active
  ? "Применить и перезапустить"
  : "Применить";


  overlay.hidden =
  false;


  ok.onclick =
  async () => {
    overlay.hidden =
    true;

    await applyStrategy(
      id
    );
  };
}


async function applyStrategy(id) {
  if (state.busy) {
    return;
  }


  /*
   * Demo mode
   */

  if (state.demoMode) {
    state.busy =
    true;

    await delay(350);

    state.strategyId =
    id;

    const strategy =
    state.strategies.find(
      (item) =>
      String(item.id) ===
      String(id)
    );

    if (strategy) {
      state.strategyName =
      strategy.name;
    }

    state.busy =
    false;

    updateStrategyHome();
    renderStrategies();

    toast(
      "Стратегия применена"
    );

    return;
  }


  state.busy =
  true;


  try {
    const result =
    await call(
      "apply_strategy",
      id
    );


    if (
      result &&
      result.ok
    ) {
      toast(
        result.message ||
        "Стратегия применена"
      );
    } else {
      toast(
        (
          result &&
          result.error
        ) ||
        "Не удалось применить стратегию",
        true
      );
    }

  } catch (error) {
    toast(
      "Ошибка: " +
      error.message,
      true
    );
  }


  state.busy =
  false;


  await refreshState();
}


/* =========================================================
 * STRATEGY EDITOR
 * ========================================================= */

let editorActiveId = null;
let editorBaseline = null;


function openEditor(strategyId) {
  editorActiveId =
  strategyId === "current"
  ? "current"
  : (strategyId || null);

  editorBaseline =
  null;

  const overlay =
  $("#editor-overlay");

  if (!overlay) {
    return;
  }


  const isNew =
  editorActiveId === null;

  const fields =
  $("#editor-fields");

  if (fields) {
    fields.hidden =
    isNew;
  }

  const deleteButton =
  $("#editor-delete");

  if (deleteButton) {
    deleteButton.hidden =
    isNew ||
    editorActiveId === "current";
  }

  const title =
  $("#editor-title");

  if (title) {
    title.textContent =
    isNew
    ? "Новая стратегия"
    : "Редактор стратегии";
  }


  setEditorResult(null);

  overlay.hidden =
  false;


  if (isNew) {
    const name =
    $("#editor-name");

    const desc =
    $("#editor-desc");

    const opt =
    $("#editor-opt");

    const mode =
    $("#editor-mode");

    if (name) {
      name.value = "";
    }

    if (desc) {
      desc.value = "";
    }

    if (opt) {
      opt.value = "";
    }

    if (mode) {
      mode.value = "hostlist";
    }

    if (opt) {
      opt.focus();
    }

    return;
  }


  fillEditorFrom(
    editorActiveId
  ).catch((error) => {
    toast(
      "Ошибка: " +
      error.message,
      true
    );

    overlay.hidden =
    true;
  });
}


async function fillEditorFrom(strategyId) {
  const name =
  $("#editor-name");

  const desc =
  $("#editor-desc");

  const opt =
  $("#editor-opt");

  const mode =
  $("#editor-mode");

  if (!name || !desc || !opt || !mode) {
    return;
  }


  const result =
  await call(
    "editor_get",
    String(strategyId)
  );

  if (!result || !result.ok) {
    throw new Error(
      (result && result.error) ||
      "Не удалось загрузить стратегию"
    );
  }


  editorBaseline =
  {
    name: result.name || "",
    description: result.description || "",
    opt: result.opt || "",
    mode_filter: result.mode_filter || "hostlist"
  };


  editorActiveId =
  String(result.id);

  name.value =
  editorBaseline.name;

  desc.value =
  editorBaseline.description;

  opt.value =
  editorBaseline.opt;

  mode.value =
  editorBaseline.mode_filter;


  const fields =
  $("#editor-fields");

  if (fields) {
    fields.hidden =
    Boolean(result.builtin);
  }

  const deleteButton =
  $("#editor-delete");

  if (deleteButton) {
    deleteButton.hidden =
    Boolean(result.builtin);
  }
}


function currentEditorPayload() {
  const name =
  $("#editor-name");

  const desc =
  $("#editor-desc");

  const opt =
  $("#editor-opt");

  const mode =
  $("#editor-mode");

  return {
    id: editorActiveId || "",
    name: name ? name.value.trim() : "",
    description: desc ? desc.value.trim() : "",
    opt: opt ? opt.value : "",
    mode_filter: mode ? mode.value : "hostlist"
  };
}


function setEditorResult(result) {
  const box =
  $("#editor-result");

  if (!box) {
    return;
  }

  if (!result) {
    box.hidden =
    true;

    box.textContent =
    "";

    box.classList.remove(
      "ok",
      "err"
    );

    return;
  }

  box.hidden =
  false;

  box.classList.toggle(
    "ok",
    Boolean(result.ok)
  );

  box.classList.toggle(
    "err",
    !result.ok
  );

  box.textContent =
  result.ok
  ? "✓ Стратегия прошла проверку"
  : "✗ " + (result.error || "Проверка не удалась") +
    (result.line
    ? " (строка " + result.line + ")"
    : "");
}


async function onEditorCheck() {
  const payload =
  currentEditorPayload();

  if (!payload.opt.trim()) {
    toast(
      "Опции пустые",
      true
    );

    return;
  }

  setEditorResult(null);

  try {
    const result =
    await call(
      "editor_validate",
      payload.opt
    );

    setEditorResult(result);
  } catch (error) {
    toast(
      "Ошибка: " +
      error.message,
      true
    );
  }
}


function onEditorReset() {
  const name =
  $("#editor-name");

  const desc =
  $("#editor-desc");

  const opt =
  $("#editor-opt");

  const mode =
  $("#editor-mode");

  if (!name || !desc || !opt || !mode) {
    return;
  }

  if (editorBaseline) {
    name.value =
    editorBaseline.name;

    desc.value =
    editorBaseline.description;

    opt.value =
    editorBaseline.opt;

    mode.value =
    editorBaseline.mode_filter;
  } else if (editorActiveId === null) {
    name.value = "";
    desc.value = "";
    opt.value = "";
    mode.value = "hostlist";
  }

  setEditorResult(null);
}


function onEditorCancel() {
  const overlay =
  $("#editor-overlay");

  if (overlay) {
    overlay.hidden =
    true;
  }

  editorActiveId =
  null;

  editorBaseline =
  null;
}


async function onEditorSave() {
  const payload =
  currentEditorPayload();

  if (!payload.opt.trim()) {
    toast(
      "Опции пустые",
      true
    );

    return;
  }

  if (state.busy) {
    return;
  }

  state.busy =
  true;


  try {
    const result =
    await call(
      "editor_save",
      payload
    );

    if (!result || !result.ok) {
      toast(
        (result && result.error) ||
        "Не удалось сохранить стратегию",
        true
      );

      return;
    }

    const overlay =
    $("#editor-overlay");

    if (overlay) {
      overlay.hidden =
      true;
    }

    editorActiveId =
    null;

    editorBaseline =
    null;

    state.strategyId =
    String(result.id || state.strategyId);

    await refreshState();

    updateStrategyHome();
    renderStrategies();

    toast(
      result.message ||
      "Стратегия сохранена"
    );
  } catch (error) {
    toast(
      "Ошибка: " +
      error.message,
      true
    );
  } finally {
    state.busy =
    false;
  }
}


function onEditorDelete() {
  const id =
  editorActiveId;

  if (!id || id === "current") {
    return;
  }


  const overlay =
  $("#dialog-overlay");

  const title =
  $("#dialog-title");

  const text =
  $("#dialog-text");

  const ok =
  $("#dialog-ok");

  const cancel =
  $("#dialog-cancel");

  if (
    !overlay ||
    !title ||
    !text ||
    !ok ||
    !cancel
  ) {
    return;
  }


  title.textContent =
  "Удалить стратегию?";

  text.textContent =
  "Стратегия будет удалена без возможности восстановления.";

  ok.textContent =
  "Удалить";

  ok.onclick =
  null;

  overlay.hidden =
  false;


  const close =
  () => {
    overlay.hidden =
    true;

    ok.classList.remove(
      "btn-danger"
    );
  };


  const onOk =
  async () => {
    close();

    try {
      const result =
      await call(
        "editor_delete",
        String(id)
      );

      if (!result || !result.ok) {
        toast(
          (result && result.error) ||
          "Не удалось удалить стратегию",
          true
        );

        return;
      }

      const editor =
      $("#editor-overlay");

      if (editor) {
        editor.hidden =
        true;
      }

      editorActiveId =
      null;

      editorBaseline =
      null;

      await refreshState();

      updateStrategyHome();
      renderStrategies();

      toast(
        result.message ||
        "Стратегия удалена"
      );
    } catch (error) {
      toast(
        "Ошибка: " +
        error.message,
        true
      );
    }
  };


  const onCancel =
  () => {
    close();

    cancel.removeEventListener(
      "click",
      onCancel
    );

    ok.removeEventListener(
      "click",
      onOk
    );
  };


  ok.classList.add(
    "btn-danger"
  );

  cancel.addEventListener(
    "click",
    onCancel
  );

  ok.addEventListener(
    "click",
    onOk
  );
}


/* =========================================================
 * MONITORING
 * ========================================================= */

async function onCheckNow() {
  if (checking) {
    return;
  }


  checking =
  true;


  const box =
  $("#monitor-results");

  const button =
  $("#btn-check-now");


  if (box) {
    box.innerHTML =
    '<p class="muted">Проверяю…</p>';
  }


  if (button) {
    button.disabled =
    true;
  }


  /*
   * Browser demo
   */

  if (state.demoMode) {
    await delay(700);


    const results = [
      {
        name: "YouTube",
        ok: true,
        ms: 42
      },
      {
        name: "Discord",
        ok: true,
        ms: 57
      },
      {
        name: "Telegram",
        ok: true,
        ms: 31
      },
      {
        name: "GitHub",
        ok: true,
        ms: 68
      }
    ];


    if (box) {
      box.innerHTML =
      results
      .map(
        (item) => `
        <div class="monitor-row">

        <span class="monitor-name">
        ${escapeHtml(
          item.name
        )}
        </span>

        <span
        class="monitor-status ${
          item.ok
          ? "ok"
          : "fail"
        }"
        >
        <span class="dot"></span>
        ${
          item.ok
          ? "доступен"
          : "недоступен"
        }
        · ${item.ms} мс
        </span>

        </div>
        `
      )
      .join("") +

      `
      <p
      class="muted"
      style="margin-top:12px"
      >
      Проверено сейчас
      </p>
      `;
    }


    checking =
    false;


    if (button) {
      button.disabled =
      false;
    }


    return;
  }


  try {
    const result =
    await call(
      "check_services"
    );


    if (
      result &&
      result.ok
    ) {
      if (box) {
        box.innerHTML =
        (result.results || [])
        .map(
          (item) => `
          <div class="monitor-row">

          <span class="monitor-name">
          ${escapeHtml(
            item.name
          )}
          </span>

          <span
          class="monitor-status ${
            item.ok
            ? "ok"
            : "fail"
          }"
          >
          <span class="dot"></span>
          ${
            item.ok
            ? "доступен"
            : "недоступен"
          }
          · ${item.ms} мс
          </span>

          </div>
          `
        )
        .join("") +

        `
        <p
        class="muted"
        style="margin-top:12px"
        >
        Проверено в ${
          escapeHtml(
            result.time ||
            "сейчас"
          )
        }
        </p>
        `;
      }

    } else {
      if (box) {
        box.innerHTML = `
        <p class="muted">
        ${
          result &&
          result.error
          ? escapeHtml(
            result.error
          )
          : "Не удалось проверить"
        }
        </p>
        `;
      }
    }

  } catch (error) {
    if (box) {
      box.innerHTML = `
      <p class="muted">
      Ошибка:
      ${escapeHtml(
        error.message
      )}
      </p>
      `;
    }
  }


  checking =
  false;


  if (button) {
    button.disabled =
    false;
  }
}


function renderMonitoring() {
  const box =
  $("#monitor-results");

  if (!box) {
    return;
  }


  if (
    box.querySelector(
      ".monitor-row"
    )
  ) {
    return;
  }


  box.innerHTML =
  '<p class="muted">Нажмите «Проверить сейчас».</p>';
}


/* =========================================================
 * SETTINGS
 * ========================================================= */

function renderSettings(data) {
  const autostart =
  $("#set-autostart");

  const interval =
  $("#set-interval");

  const theme =
  $("#set-theme");


  const zapret =
  (data && data.zapret) ||
  {};

  const system =
  (data && data.system) ||
  {};


  if (autostart) {
    autostart.checked =
    Boolean(
      zapret.service_enabled
    );
  }


  if (interval) {
    interval.value =
    store.get(
      "interval"
    ) ||
    "5";
  }


  if (theme) {
    theme.value =
    store.get(
      "theme"
    ) ||
    "auto";
  }


  const about =
  $("#about-line");

  if (about) {
    about.textContent =
    `ZapretGUI 0.1.0 · ` +
    `${system.distro || "Linux"} ` +
    `${system.arch || ""} · ` +
    `zapret2 ${zapret.version || "—"}`;
  }
}


function initSettings() {
  const autostart =
  $("#set-autostart");

  const interval =
  $("#set-interval");

  const theme =
  $("#set-theme");


  if (autostart) {
    autostart.addEventListener(
      "change",
      async () => {
        if (state.demoMode) {
          toast(
            "Настройка доступна только в приложении"
          );

          return;
        }


        const value =
        autostart.checked;


        try {
          const result =
          await call(
            "set_enabled_autostart",
            value
          );


          if (
            result &&
            result.ok
          ) {
            toast(
              "Настройка сохранена"
            );
          } else {
            autostart.checked =
            !value;

            toast(
              (
                result &&
                result.error
              ) ||
              "Не удалось сохранить",
              true
            );
          }

        } catch (error) {
          autostart.checked =
          !value;

          toast(
            "Ошибка: " +
            error.message,
            true
          );
        }
      }
    );
  }


  if (interval) {
    interval.addEventListener(
      "change",
      () => {
        store.set(
          "interval",
          interval.value
        );

        toast(
          `Интервал проверок: ${interval.value} минут`
        );
      }
    );
  }


  if (theme) {
    theme.addEventListener(
      "change",
      () => {
        store.set(
          "theme",
          theme.value
        );

        applyTheme();
      }
    );
  }
}


/* =========================================================
 * HOME STRATEGY
 * ========================================================= */

function updateStrategyHome() {
  const name =
  $("#strategy-name");

  const desc =
  $("#strategy-desc");


  const strategy =
  state.strategies.find(
    (item) =>
    String(item.id) ===
    String(state.strategyId)
  );


  if (name) {
    name.textContent =
    state.strategyName ||
    "—";
  }


  if (desc) {
    desc.textContent =
    strategy
    ? strategy.description || ""
    : "";
  }
}


/* =========================================================
 * REAL BACKEND STATE
 * ========================================================= */

async function refreshState() {
  if (state.demoMode) {
    return;
  }


  try {
    const data =
    await call(
      "get_state"
    );


    if (!data) {
      return;
    }


    const zapret =
    data.zapret ||
    {};

    const strategy =
    data.strategy ||
    {};

    const system =
    data.system ||
    {};


    /* ---------------------------------
     *     Backend is alive
     *     --------------------------------- */

    state.backendReady =
    true;


    /* ---------------------------------
     *     Zapret
     *     --------------------------------- */

    state.zapretFound =
    Boolean(
      zapret.found
    );


    /* ---------------------------------
     *     Strategy
     *     --------------------------------- */

    state.strategyId =
    strategy.id ||
    "auto";


    state.strategyName =
    strategy.name ||
    "—";


  state.strategies =
  Array.isArray(
    strategy.available
  )
  ? strategy.available
  : [];


  /* ---------------------------------
   *     Status
   *     --------------------------------- */

  state.status =
  data.status ||
  "inactive";


    setStatus(
      state.status
    );


    renderPower();


    /* ---------------------------------
     *     Home strategy
     *     --------------------------------- */

    updateStrategyHome();


    /* ---------------------------------
     *     Install warning
     *     --------------------------------- */

    const install =
    $("#warn-install");

    if (install) {
      install.hidden =
      state.zapretFound;
    }


    /* ---------------------------------
     *     Error warning
     *     --------------------------------- */

    const errorCard =
    $("#warn-error");

    if (errorCard) {
      errorCard.hidden =
      true;
    }


    /* ---------------------------------
     *     Meta
     *     --------------------------------- */

    const meta =
    $("#meta-line");


    if (meta) {
      if (
        state.status ===
        "active"
      ) {
        meta.textContent =
        "Защита активна · Автозапуск " +
        (
          zapret.service_enabled
          ? "включён"
          : "выключен"
        );
      }

      else if (
        state.status ===
        "degraded"
      ) {
        meta.textContent =
        "Защита работает с проблемами";
      }

      else if (
        state.status ===
        "error"
      ) {
        if (
          !state.zapretFound
        ) {
          meta.textContent =
          "zapret2 не установлен";
        }

        else if (
          system.systemd ===
          false
        ) {
          meta.textContent =
          "systemd не обнаружен — ZapretGUI требует systemd";
        }

        else {
          meta.textContent =
          "Произошла ошибка";
        }

      } else {
        meta.textContent =
        "Защита выключена";
      }
    }


    /* ---------------------------------
     *     Warnings
     *     --------------------------------- */

    if (
      Array.isArray(
        zapret.warnings
      ) &&
      zapret.warnings.length
    ) {
      const errorText =
      $("#error-text");

      if (errorText) {
        errorText.textContent =
        zapret.warnings[0];
      }

      if (errorCard) {
        errorCard.hidden =
        false;
      }
    }


    /* ---------------------------------
     *     Settings
     *     --------------------------------- */

    renderSettings(
      data
    );


    /* ---------------------------------
     *     Strategies
     *     --------------------------------- */

    renderStrategies();

  } catch (error) {
    /*
     * Не считаем это фатальной ошибкой.
     * UI продолжает работать.
     */

    console.error(
      "refreshState:",
      error
    );


    setStatus(
      "error"
    );


    const hint =
    $("#status-hint");

    if (hint) {
      hint.textContent =
      "Backend недоступен: " +
      error.message;
    }
  }
}


/* =========================================================
 * DEMO MODE
 * ========================================================= */

function enableDemoMode() {
  state.demoMode =
  true;

  state.backendReady =
  false;

  state.zapretFound =
  true;

  state.status =
  "inactive";


    state.strategyId =
    "auto";


    state.strategyName =
    "Автоматическая";


    state.strategies = [
      {
        id: "auto",

        name: "Автоматическая",

        description:
        "Оптимальная стратегия для большинства соединений."
      },

      {
        id: "general",

        name: "Общая",

        description:
        "Универсальная стратегия обхода блокировок."
      },

      {
        id: "aggressive",

        name: "Агрессивная",

        description:
        "Более интенсивный вариант обхода DPI."
      },

      {
        id: "safe",

        name: "Безопасная",

        description:
        "Минимальное вмешательство в сетевое соединение."
      }
    ];


    setStatus(
      state.status
    );

    renderPower();

    updateStrategyHome();

    renderStrategies();


    const meta =
    $("#meta-line");

    if (meta) {
      meta.textContent =
      "Режим предпросмотра · backend не подключён";
    }


    const install =
    $("#warn-install");

    if (install) {
      install.hidden =
      true;
    }


    renderSettings({
      zapret: {
        found: true,
        service_enabled: false,
        version: "preview"
      },

      system: {
        distro: "Linux",
        arch: "x86_64"
      }
    });
}


/* =========================================================
 * TOAST
 * ========================================================= */

function toast(
  text,
  error = false
) {
  const container =
  $("#toasts");

  if (!container) {
    return;
  }


  const element =
  document.createElement(
    "div"
  );


  element.className =
  "toast" +
  (
    error
    ? " error"
    : ""
  );


  element.textContent =
  text;


  container.appendChild(
    element
  );


  setTimeout(
    () => {
      element.remove();
    },
    3500
  );
}


/* =========================================================
 * UTILS
 * ========================================================= */

function delay(ms) {
  return new Promise(
    (resolve) =>
    setTimeout(
      resolve,
      ms
    )
  );
}


function escapeHtml(value) {
  if (
    value === null ||
    value === undefined
  ) {
    return "";
  }


  return String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");
}


/* =========================================================
 * INITIALIZATION
 * ========================================================= */

function initApp() {
  /*
   * Защита от двойной инициализации.
   */

  if (appInitialized) {
    return;
  }

  appInitialized =
  true;


  /* Theme */

  initTheme();


  /* ---------------------------------
   *   Navigation
   *   --------------------------------- */

  document
  .querySelectorAll(
    ".dock-item"
  )
  .forEach((button) => {
    button.addEventListener(
      "click",
      () => {
        navigate(
          button.dataset.route
        );
      }
    );
  });


  document
  .querySelectorAll(
    "[data-route]:not(.dock-item)"
  )
  .forEach((button) => {
    button.addEventListener(
      "click",
      () => {
        navigate(
          button.dataset.route
        );
      }
    );
  });


  /* ---------------------------------
   *   Power
   *   --------------------------------- */

  $("#power-btn")?.addEventListener(
    "click",
    onPower
  );


  /* ---------------------------------
   *   Strategy card
   *   --------------------------------- */

  $("#strategy-card")?.addEventListener(
    "click",
    () => navigate(
      "strategies"
    )
  );


  /* ---------------------------------
   *   Install
   *   --------------------------------- */

  $("#btn-install")?.addEventListener(
    "click",
    () => {
      toast(
        "Установка zapret2 появится в следующей версии."
      );
    }
  );


  /* ---------------------------------
   *   Retry
   *   --------------------------------- */

  $("#btn-retry")?.addEventListener(
    "click",
    refreshState
  );


  /* ---------------------------------
   *   Diagnostics
   *   --------------------------------- */

  $("#btn-goto-diag")?.addEventListener(
    "click",
    () => navigate(
      "diagnostics"
    )
  );


  /* ---------------------------------
   *   Monitoring
   *   --------------------------------- */

  $("#btn-check-now")?.addEventListener(
    "click",
    onCheckNow
  );


  /* ---------------------------------
   *   Strategy editor
   *   --------------------------------- */

  $("#btn-new-strategy")?.addEventListener(
    "click",
    () => openEditor(null)
  );

  $("#editor-check")?.addEventListener(
    "click",
    onEditorCheck
  );

  $("#editor-reset")?.addEventListener(
    "click",
    onEditorReset
  );

  $("#editor-cancel")?.addEventListener(
    "click",
    onEditorCancel
  );

  $("#editor-save")?.addEventListener(
    "click",
    onEditorSave
  );

  $("#editor-delete")?.addEventListener(
    "click",
    onEditorDelete
  );


  const editorOverlay =
  $("#editor-overlay");

  editorOverlay?.addEventListener(
    "click",
    (event) => {
      if (
        event.target ===
        editorOverlay
      ) {
        editorOverlay.hidden =
        true;

        editorActiveId =
        null;

        editorBaseline =
        null;
      }
    }
  );


  /* ---------------------------------
   *   Dialog
   *   --------------------------------- */

  const overlay =
  $("#dialog-overlay");

  const cancel =
  $("#dialog-cancel");


  cancel?.addEventListener(
    "click",
    () => {
      overlay.hidden =
      true;
    }
  );


  overlay?.addEventListener(
    "click",
    (event) => {
      if (
        event.target ===
        overlay
      ) {
        overlay.hidden =
        true;
      }
    }
  );


  document.addEventListener(
    "keydown",
    (event) => {
      if (
        event.key ===
        "Escape"
      ) {
        if (
          overlay &&
          !overlay.hidden
        ) {
          overlay.hidden =
          true;
        }
      }
    }
  );


  /* ---------------------------------
   *   Routing
   *   --------------------------------- */

  window.addEventListener(
    "hashchange",
    renderRoute
  );


  renderRoute();


  /* ---------------------------------
   *   Settings
   *   --------------------------------- */

  initSettings();


  /*
   * Если API уже существует,
   * сразу подключаем backend.
   *
   * Это важно при pywebview,
   * где pywebviewready мог прийти
   * до выполнения этого кода.
   */

  if (api()) {
    connectBackend();
  } else {
    /*
     * Обычный Firefox / Chrome.
     */

    enableDemoMode();
  }
}


/* =========================================================
 * BACKEND CONNECTION
 * ========================================================= */

function connectBackend() {
  if (
    !api()
  ) {
    return;
  }


  /*
   * Выключаем demo mode.
   */

  state.demoMode =
  false;

  state.backendReady =
  true;


  /*
   * Если старый таймер существовал —
   * удаляем его.
   */

  if (refreshTimer) {
    clearInterval(
      refreshTimer
    );

    refreshTimer =
    null;
  }


  /*
   * Получаем настоящее состояние.
   */

  refreshState();


  /*
   * Периодическое обновление.
   */

  refreshTimer =
  setInterval(
    () => {
      if (
        document.hidden ||
        state.busy ||
        checking
      ) {
        return;
      }

      refreshState();
    },
    15000
  );
}


/* =========================================================
 * DOM READY
 * ========================================================= */

if (
  document.readyState ===
  "loading"
) {
  document.addEventListener(
    "DOMContentLoaded",
    initApp,
    {
      once: true
    }
  );
} else {
  initApp();
}


/* =========================================================
 * PYWEBVIEW READY
 * ========================================================= */

/*
 * В pywebview API может появиться
 * ПОСЛЕ DOMContentLoaded.
 *
 * Поэтому здесь повторно подключаемся
 * к Python backend.
 */

window.addEventListener(
  "pywebviewready",
  () => {
    connectBackend();
  },
  {
    once: true
  }
);
