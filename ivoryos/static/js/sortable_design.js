// Move triggerModal to global scope
function triggerModal(formHtml, actionName, actionId, dropTargetId) {
    if (formHtml && formHtml.trim() !== "") {
        var $wrapper = $("<div>").html(formHtml);

        var $hiddenInput = $("<input>")
            .attr("type", "hidden")
            .attr("name", "drop_target_id")
            .attr("id", "dropTargetInput")
            .val(dropTargetId);

        // This copy of the toolbox form gets an id of its own, so the footer's Add (beside
        // Cancel) submits it rather than the toolbox form it was copied from.
        var $form = $wrapper.find("form").first();
        $form.attr("id", "dropModalForm");
        $form.find("button[type='submit']").remove();
        $form.append($hiddenInput);

        $("#modalFormFields").empty().append($wrapper.children());

        const $modal = $("#dropModal");

        setTimeout(() => {
            showModal($modal);
        }, 0);

        $("#modalDropTarget").text(dropTargetId || "N/A");
        $("#modalFormFields")
            .data("action-id", actionId)
            .data("action-name", actionName)
            .data("drop-target-id", dropTargetId);

        // Fetch valid variables for this position (a dict argument's textarea too: its table takes
        // its suggestions from it, see structured_editor.js)
        const datalistId = "modal_vars_" + Date.now();
        $("#modalFormFields").find("[list='variables_datalist']").attr("list", datalistId);

        fetch(variablesUrl + "?before_id=" + (dropTargetId || ""))
            .then(res => res.json())
            .then(data => {
                const $datalist = $("<datalist>").attr("id", datalistId);
                data.variables.forEach(v => {
                    $datalist.append($("<option>").val(v).text(v));
                });
                $("#modalFormFields").append($datalist);
            })
            .catch(console.error);
    } else {
        console.error("Form HTML is undefined or empty!");
    }
}

function showModal($modal) {
    $modal.modal({
        backdrop: 'static',
        keyboard: true,
        focus: true
    }).modal('show');
}

const state = {
    dropTargetId: ""
};

window.isSorting = false;

function initializeCanvas() {
    $("#list ul").sortable({
        cancel: ".unsortable",
        opacity: 0.8,
        cursor: "move",
        placeholder: "drop-placeholder",
        start: function (event, ui) {
            window.isSorting = true;
        },
        stop: function (event, ui) {
            setTimeout(() => {
                window.isSorting = false;
            }, 100);
        },
        update: function () {
            const item_order = $("ul.reorder li").map(function () {
                return this.id;
            }).get();
            var order_string = "order=" + item_order.join(",");

            $.ajax({
                method: "POST",
                url: updateListUrl,
                data: order_string,
                cache: false,
                success: function (data) {
                    // Update the canvas content with the new HTML: the old order when the move
                    // was refused (an else dragged above its own if), which the warning explains
                    updateActionCanvas(data);
                    if (typeof showWarningIfExists === "function") showWarningIfExists(data);
                    if (typeof refreshSidebarVariables === "function") {
                        refreshSidebarVariables();
                    }
                }
            }).fail(function (jqXHR, textStatus, errorThrown) {
                console.error("Failed to update order:", textStatus, errorThrown);
            });
        }
    });

    $("#list ul, .canvas").off("dragover").on("dragover", function (event) {
        event.preventDefault();
        let $target = $(event.target).closest("li");

        if ($target.length) {
            state.dropTargetId = $target.attr("id") || "";
            insertDropPlaceholder($target);
        } else if (!$("#list ul").children().length && $(this).hasClass("canvas")) {
            $(".drop-placeholder").remove();
        } else {
            state.dropTargetId = "";
        }
    });

    $("#list ul, .canvas").off("dragleave").on("dragleave", function () {
        $(".drop-placeholder").remove();
    });

    $("#list ul, .canvas").off("drop").on("drop", function (event) {
        event.preventDefault();
        var actionName = event.originalEvent.dataTransfer.getData("action");
        var actionId = event.originalEvent.dataTransfer.getData("id");
        var formHtml = event.originalEvent.dataTransfer.getData("form");
        let listLength = $("ul.reorder li").length;
        state.dropTargetId = state.dropTargetId || listLength + 1;
        $(".drop-placeholder").remove();
        document.activeElement?.blur();
        triggerModal(formHtml, actionName, actionId, state.dropTargetId);
    });
    initializeStepIssueTooltips();
    getCodePreview();
    // what undo and redo would do now came with the canvas (see draft_history.js)
    if (typeof syncHistoryControls === "function") syncHistoryControls();
}

// The canvas is re-rendered as raw HTML on every edit, so the tooltips that
// explain why a step no longer matches the deck have to be bound again each time.
// Hover is the only trigger that works here: the list is a jQuery UI sortable,
// which calls preventDefault on mousedown and so suppresses focus.
function initializeStepIssueTooltips() {
    if (typeof bootstrap === "undefined") return;

    // a shown tooltip lives on <body>, so it outlives the step that opened it
    document.querySelectorAll("body > .tooltip.step-issue-tooltip").forEach(el => el.remove());

    document.querySelectorAll('#canvas-action-wrapper [data-bs-toggle="tooltip"]').forEach(el => {
        bootstrap.Tooltip.getInstance(el)?.dispose();
        new bootstrap.Tooltip(el, { container: "body", trigger: "hover" });
    });
}

function insertDropPlaceholder($target) {
    $(".drop-placeholder").remove();
    $("<li class='drop-placeholder'></li>").insertBefore($target);
}

// The toolbox's actions drag onto the canvas; called again whenever a group loads its actions
function initializeDragHandlers() {
    const $cards = $(".toolbox-action");

    // An action drags by its row; its open form stays free for typing and selecting text
    $cards.off("mousedown touchstart").on("mousedown touchstart", function (event) {
        this.setAttribute("draggable", $(event.target).closest(".toolbox-action-toggle").length ? "true" : "false");
    });

    // Handle the actual drag
    $cards.off("dragstart dragend").on({
        dragstart: function (event) {
            if (this.getAttribute("draggable") !== "true") {
                event.preventDefault();
                return false;
            }

            const formHtml = $(this).find(".toolbox-action-body form").prop("outerHTML");
            if (!formHtml) return false;

            event.originalEvent.dataTransfer.setData("form", formHtml);
            event.originalEvent.dataTransfer.setData("action", $(this).find(".toolbox-action-toggle").data("action"));
            event.originalEvent.dataTransfer.setData("id", $(this).find(".toolbox-action-toggle").attr("aria-controls"));

            $(this).addClass("dragging");
        },
        dragend: function () {
            $(this).removeClass("dragging").attr("draggable", "false");
        }
    });

    // Prevent form inputs from being draggable
    $(".toolbox-action input, .toolbox-action select").attr("draggable", "false");
}

// Make sure it's called in the document ready function
$(document).ready(function () {
    initializeCanvas();
    initializeDragHandlers(); // Add this line
});