/*
 * Control code for single-page thermostat app.
 *
 * This code could potentially be rewritten to use a JS framework providing
 * MVC, but the simplicity of the first version didn't seem to merit it.
 */

/* global load_summary */

var weekday = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday"
};

/* Clear existing override */
function clear_override() {
    $.ajax({
        url: 'api//target_override',
        type: 'DELETE',
        success: function() {
            load_summary();
        }});
}

/* Make UI elements for the override dialog
 *
 * override_set_ev is the function to call when an override is set. */
function mk_override(override_set_ev) {
    var cancel_click = function() {
        $("#override").hide();
    };
    var override_submit = function() {
        var hours_val = $("#override_hours").val();
        var temp_val = $("#override_temp").val();
        $.post({
            url: "api//target_override",
            data: {hours: hours_val, temp: temp_val},
            success: function(data) { override_set_ev(); }
        });
        return false;
    };

    var override = $("<div>").addClass("modal")
                             .attr('id', 'override');
    override.html(
        '<div class="modal-content">' +
            '<h1>Set override</h1>' +
            '<form><label>Set target:</label> ' +
            '<input id="override_temp" type="number" step="any">&deg;C<br /> ' +
            '<label>Duration:</label> ' +
            '<input id="override_hours" type="number" /> hours' +
            '<div class="buttons">' +
                '<button id="override_cancel" ' +
                        'class="flat">Cancel</button>' +
                '<input type="submit" class="flat" ' +
                       'value="Override" />' +
            '</div>' +
        '</div>');
    $(override).find("#override_cancel").click(cancel_click);
    $(override).find("form").submit(override_submit);
    return override;
}

/* Generates a list of DOM objects representing UI for a day's schedule.
 * sched is an array object with each entry being an object with a time and
 *       temp field.
 * dow is the 0-based day of week being rendered
 * highlighted_entry is the index of a highlighted entry
 * editable is a flag indicating whether to include controls to edit the
 *          schedule. */
/* exported renderSchedule */
function renderSchedule(sched, dow, highlighted_entry, editable) {
    var mk_row = function(start, end, temp) {
        var tr = $("<tr>");
        var td_start = $("<td>").text(start);
        var td_end = $("<td>").text(end);
        var td_temp = $("<td>").text(temp);
        var td_remove = $("<td>").addClass("remove");
        var remove_btn = $("<button>");
        remove_btn.addClass("flat").text("Remove");
        remove_btn.data("time", start);
        remove_btn.data("day", dow);
        remove_btn.data("tablerow", tr);
        remove_btn.click(remove_click);
        td_remove.append(remove_btn);

        tr.append(td_start);
        if (!editable)
            tr.append(td_end);
        tr.append(td_temp);
        if (editable)
            tr.append(td_remove);

        return tr;
    };
    var add_click = function() {
        var timeval = $("#time_" + dow)[0].value;
        var tempval = $("#temp_" + dow)[0].value;
        /* This kinda sucks: find right place in table to put the value: */
        var pos = 1;
        for (var i = 0; i < sched.length; i++) {
            /* All time in %H:%M format, 24h clock, so this works.
             * But it's super ugly. */
            if (sched[i].time < timeval) {
                pos += 1;
            }
        }
        sched.splice(pos - 1, 0, {time: timeval, temp: tempval});

        var tr = mk_row(timeval, null, tempval);
        $.post({url: "api/schedule/new_entry",
                data: {time: timeval, temp: tempval, day: dow},
                success: function() {
                        $(table_sched).find("tr").eq(pos - 1).after(tr);
                        $("#time_" + dow).val("");
                        $("#temp_" + dow).val("");
                        $("#time_" + dow).focus();
                    }
               });
    };
    var remove_click = function() {
        var timeval = $(this).data().time;
        var dayval = $(this).data().day;
        var tr = $(this).data("tablerow");
        var data = {time: timeval, day: dayval};
        $.post({
            url: "api/schedule/delete_entry",
            data: data,
            success: function() {
                    tr.remove();
                    sched.splice(sched.findIndex(function(x) { return x.time == data.time; } ), 1);
                }
            });
    };

    var div_sched = [];
    div_sched.push($("<h1>").text(weekday[dow]));
    var table_sched = $("<table>");
    var head = $("<tr>").append($("<td>").text("Start"));
    if (!editable)
        head.append($("<td>").text("End"));
    head.append($("<td>").text("Target"));
    head.addClass("head");
    if (editable)
        head.append($("<td>"));
    table_sched.append(head);
    for (var i = 0; i < sched.length; i++) {
        var tr = mk_row(sched[i].time,
                        i < sched.length - 1 ? sched[i + 1].time : "tomorrow",
                        sched[i].temp);
        if (highlighted_entry == i)
            tr.addClass("active");
        table_sched.append(tr);
    }

    /* And row for adding new content */
    if (editable) {
        var tr_add = $("<tr>");
        var keyfn = function(e) {
            if (e.which == 13)
                $("button#add_" + dow).click();
        };
        var timefield = $('<input type="time" placeholder="HH:MM">');
        timefield.attr("id", "time_" + dow);
        timefield.keypress(keyfn);

        var tempfield = $('<input type="number" step="any" placeholder="Celsius">');
        tempfield.attr("id", "temp_" + dow);
        tempfield.keypress(keyfn);

        var td_add_time = $("<td>").append(timefield);
        var td_add_temp = $("<td>").append(tempfield);
        var add_btn = $('<button class="flat">Add</button>');
        add_btn.data("timefield", timefield);
        add_btn.data("tempfield", tempfield);
        add_btn.attr("id", "add_" + dow);
        add_btn.click(add_click);
        var td_add = $("<td>").append(add_btn);
        tr_add.append(td_add_time);
        tr_add.append(td_add_temp);
        tr_add.append(td_add);
        table_sched.append(tr_add);
    }

    div_sched.push(table_sched);

    return div_sched;
}

/* Updates the application with a full, editable, schedule.
 * schedule is an array object containing the schedule, i.e. each at
 *          index is an object with a time and temp field. */
/* exported renderFullSchedule */
function renderFullSchedule(schedule) {
    /* Set up app title bar: */
    $("#title").html('<a href="#summary"><i class="material-icons">' +
                     'arrow_back</i></a> Edit Schedule');
    var schedule_div = $("<div>").attr('id', 'app');
    schedule = schedule.schedule;

    /* Render each day's schedule */
    for (var i = 0; i < 7; i++) {
        var day = renderSchedule(schedule[i], i, -1, true);
        var day_card = $("<div>").append(day);
        day_card.addClass("tablecard").addClass("card");
        schedule_div.append(day_card);
    }

    $("#app").replaceWith(schedule_div);
}

/* Replaces the app window contents with a summary view.
 * summary is a summary object provided by the server, with fields:
 *    current: the current temperature
 *    target: the target temperature
 *    target_overridden: true if an override is in place
 *    server_day_of_week: the current day of week according to the server
 *    target_entry: index of the current active entry
 *    today: full schedule for today. */
/* exported renderSummary */
function renderSummary(summary) {
    /* Set up app title bar: */
    $("#title").text("Today");

    var schedule_div = $("<div>").attr('id', 'app');

    // Current and target temperatures
    var current_val = summary.current ? summary.current.toFixed(1) : "---";
    var current = $("<div>").attr("id", "current");
    current.append($("<h1>").text(current_val).append("&deg;C"));

    var target = $("<p>").text(
        summary.target == null ? "---" : summary.target.toString());
    target.prepend(summary.target_overridden ? "Override: "
                                             : "Target: ")
          .append("&deg;C")
          .attr("id", "target");
    current.append(target);
    var until = new Date(summary.target_override.until);
    if (summary.target_overridden)
        target.append(" until " + until.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}));
    schedule_div.append(current);

    var page = $("<div>").addClass("page");
    page.append(renderSchedule(summary.today,
                               summary.server_day_of_week,
                               summary.target_entry));
    page.append('<div class="buttons">' +
                '<button onclick="window.location.hash = ' +
                ' \'#edit_schedule\'" class="flat">Edit Schedule</button>' +
                '</div>');
    page.append(mk_override(load_summary));

    /* Override */
    if (summary.target_overridden) {
        schedule_div.append(
            $("<button>").addClass("floating")
                         .html('<i class="material-icons">clear</i>')
                         .click(clear_override));
    } else {
        var override_click = function() {
            $("#override").show();
        };
        schedule_div.append(
            $("<button>").addClass("floating")
                         .html('<i class="material-icons">mode_edit</i>')
                         .click(override_click));
    }

    schedule_div.append(page);

    $("#app").replaceWith(schedule_div);
}

