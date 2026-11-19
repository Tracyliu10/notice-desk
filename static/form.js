const cm = document.querySelector("#cm");
if (cm) {
    cm.addEventListener("change", () => {
        document.querySelector("#phone").value = cm.selectedOptions[0].dataset.phone || "";
    });
}

const entity = document.querySelector("#entity-filter");
if (entity) {
    const kind = document.querySelector("#kind");
    const groups = [...kind.querySelectorAll("optgroup")];
    const blankOption = kind.querySelector("option");
    const createButton = entity.form.querySelector("button[type=submit], button:not([type])");
    const filter = () => {
        kind.replaceChildren(blankOption, ...groups.filter(group => group.dataset.entity === entity.value));
        kind.value = "";
        kind.disabled = !entity.value;
        createButton.disabled = true;
    };
    kind.addEventListener("change", () => {
        createButton.disabled = !kind.value;
    });
    entity.addEventListener("change", filter);
    filter();
}

const grounds = document.querySelector("#ground");
const breachFields = document.querySelector("#rta-breach-fields");
if (grounds && breachFields) {
    const update = () => {
        breachFields.hidden = grounds.value !== "6";
        breachFields.querySelectorAll("input").forEach(input => {
            input.disabled = breachFields.hidden;
        });
    };
    grounds.addEventListener("change", update);
    update();
}

const noticeEdit = document.querySelector("#notice-edit");
if (noticeEdit) {
    const {date, days, due, ground, lease_term: term, lease_end: leaseEnd,
        agreement_days: agreementDays, delivery, service_date: postalDate, manual_vacate: manualVacate} = noticeEdit.elements;
    const kind = noticeEdit.dataset.kind;
    const termDependent = JSON.parse(noticeEdit.dataset.termDependent);
    const groundDays = JSON.parse(noticeEdit.dataset.groundDays);
    const periodMessage = document.querySelector("#calculated-period");
    const manualPeriod = document.querySelector("#manual-period");
    const showField = (id, show) => {
        const field = document.getElementById(id);
        if (field) field.hidden = !show;
    };
    const updateDue = () => {
        const selectedGround = ground?.value;
        const postal = postalDate && delivery.value === "1";
        const termNeeded = kind === "rta-end" && (selectedGround === "0" || termDependent.includes(selectedGround));
        const endNeeded = termNeeded && ["short", "long"].includes(term.value);
        showField("postal-delivery", postal);
        showField("lease-fields", termNeeded);
        showField("lease-end-field", endNeeded);
        showField("agreement-days-field", selectedGround === "8");
        const ruleBased = kind.endsWith("-rent") || kind.endsWith("-end");
        if (manualPeriod) manualPeriod.hidden = ruleBased;

        let period = days?.value === "" || !days ? null : Number(days.value);
        if (kind === "rta-rent") period = 60;
        if (kind === "oa-rent") period = 28;
        if (kind.endsWith("-end")) period = groundDays[selectedGround] ?? null;
        if (kind === "rta-end") {
            if (termDependent.includes(selectedGround) && term.value) period = term.value === "short" ? 60 : 90;
            if (selectedGround === "8" && /^\d{1,4}$/.test(agreementDays.value)) {
                period = Math.max(30, Number(agreementDays.value));
            }
        }
        periodMessage.textContent = period === null
            ? (kind.endsWith("-end") ? "Select the reason and any applicable agreement details to calculate the notice period." : "")
            : `Notice period: ${period} calendar ${period === 1 ? "day" : "days"} from delivery. Delivery day is day zero.`;

        if (manualVacate?.checked) {
            due.readOnly = false;
            return;
        }
        const wasAutomatic = due.readOnly;
        due.readOnly = ruleBased || period !== null;
        if (!due.readOnly) {
            if (wasAutomatic) due.value = "";
            return;
        }
        due.value = "";
        const start = (postal ? postalDate : date).valueAsDate;
        if (!start || period === null || (termNeeded && !term.value) || (endNeeded && !leaseEnd.value)) return;
        start.setUTCDate(start.getUTCDate() + period);
        due.valueAsDate = endNeeded && leaseEnd.valueAsDate > start ? leaseEnd.valueAsDate : start;
    };
    for (const field of [date, days, ground, term, leaseEnd, agreementDays, delivery, postalDate, manualVacate]) {
        field?.addEventListener("input", updateDue);
    }
    updateDue();
}

const oaReason = document.querySelector('[name="oa_reason"]');
if (oaReason) {
    const other = document.querySelector("#oa-other-reason");
    const clause = oaReason.form.elements.provision;
    const mapping = JSON.parse(oaReason.dataset.clauseMapping);
    const update = () => {
        other.hidden = oaReason.value !== "other";
    };
    oaReason.addEventListener("change", () => {
        clause.value = mapping[oaReason.value] || "";
        update();
    });
    if (!clause.value.trim()) clause.value = mapping[oaReason.value] || "";
    update();
}

const signingForm = document.querySelector("#signing-form");
if (signingForm) {
    const pad = document.querySelector("#signature-pad");
    const context = pad.getContext("2d");
    const message = document.querySelector("#signature-message");
    const field = document.querySelector("#signature-data");
    const strokes = [];
    let activePointer = null;
    let pointCount = 0;
    context.lineWidth = 3.5;
    context.strokeStyle = context.fillStyle = "#142437";
    context.lineCap = "round";

    const position = (event) => {
        const bounds = pad.getBoundingClientRect();
        const clamp = (value) => Math.max(0, Math.min(1, value));
        return [
            Number(clamp((event.clientX - bounds.left) / bounds.width).toFixed(4)),
            Number(clamp((event.clientY - bounds.top) / bounds.height).toFixed(4)),
        ];
    };

    pad.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || activePointer !== null || strokes.length >= 100 || pointCount >= 2400) return;
        activePointer = event.pointerId;
        pad.setPointerCapture(activePointer);
        const point = position(event);
        strokes.push([point]);
        pointCount++;
        context.beginPath();
        context.arc(point[0] * pad.width, point[1] * pad.height, 1.75, 0, Math.PI * 2);
        context.fill();
        message.textContent = "";
    });

    pad.addEventListener("pointermove", (event) => {
        if (activePointer !== event.pointerId || pointCount >= 2400) return;
        const stroke = strokes.at(-1);
        const last = stroke.at(-1);
        const next = position(event);
        if (Math.hypot(next[0] - last[0], next[1] - last[1]) < .001) return;
        context.beginPath();
        context.moveTo(last[0] * pad.width, last[1] * pad.height);
        context.lineTo(next[0] * pad.width, next[1] * pad.height);
        context.stroke();
        stroke.push(next);
        pointCount++;
    });

    for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) {
        pad.addEventListener(eventName, (event) => {
            if (activePointer === event.pointerId) activePointer = null;
        });
    }

    document.querySelector("#signature-clear").addEventListener("click", () => {
        strokes.length = 0;
        activePointer = null;
        pointCount = 0;
        field.value = "";
        context.clearRect(0, 0, pad.width, pad.height);
        message.textContent = "Signature cleared.";
    });

    signingForm.addEventListener("submit", (event) => {
        const points = strokes.flat();
        const spread = (index) => {
            const values = points.map(point => point[index]);
            return Math.max(...values) - Math.min(...values);
        };
        if (!points.length || Math.max(spread(0), spread(1)) < .025) {
            event.preventDefault();
            message.textContent = "Draw your signature before confirming.";
            return;
        }
        field.value = JSON.stringify(strokes);
    });
}

const otherClause = document.querySelector("#rta-other-clause");
if (otherClause) {
    const customClauses = [...document.querySelectorAll('[name="clauses"]')]
        .filter(input => ["Smoking", "Balcony laundry", "Other"].includes(input.value));
    const update = () => {
        otherClause.hidden = !customClauses.some(input => input.checked)
            && !otherClause.querySelector("textarea").value.trim();
    };
    customClauses.forEach(input => input.addEventListener("change", update));
    update();
}

document.querySelector("#delete-notice")?.addEventListener("submit", (event) => {
    if (!window.confirm("Delete this notice? It will be removed from your list and the CM review queue.")) {
        event.preventDefault();
    }
});

const invalidField = noticeEdit?.querySelector('[aria-invalid="true"]');
if (invalidField) {
    const focusTarget = invalidField.matches("fieldset") ? invalidField.querySelector("input") : invalidField;
    focusTarget?.focus();
}

const memberRole = document.querySelector("#member-role");
if (memberRole) {
    const row = document.querySelector("#member-phone-row");
    const phone = memberRole.form.elements.phone;
    const update = () => {
        row.hidden = memberRole.value !== "cm";
        phone.required = !row.hidden;
        phone.disabled = row.hidden;
    };
    memberRole.addEventListener("change", update);
    update();
}
