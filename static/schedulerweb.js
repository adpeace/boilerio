/*
 * Control code for single-page thermostat app.
 *
 * This has grown from a simple page where MVC/similar frameworks were overkill
 * to a state where it would greatly benefit from a better structure.
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
function mk_override(override_set_ev, zones) {
    var cancel_click = function() {
        $("#override").hide();
    };
    var override_submit = function() {
        var hours_val = $("#override_hours").val();
        var temp_val = $("#override_temp").val();
        var zone_val = $("#override_zone").val();
        $.post({
            url: "api//target_override",
            data: {hours: hours_val, temp: temp_val, zone: zone_val},
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
            '<input id="override_temp" type="number">&deg;C<br /> ' +
            '<label>Zone</label>' +
            '<select id="override_zone"></select><br />' +
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
    $.each(zones, function(i, zone) {
        $(override).find("#override_zone").append($("<option>", {value: zone.zone_id, text: zone.name}));
    });
    $(override).find("form").submit(override_submit);
    return override;
}

/* Generates a list of DOM objects representing UI for a day's schedule.
 * sched is an array object with each entry being an object with a time and
 *       temp field.
 * zones is an array of zone_id -> zone_object
 * dow is the 0-based day of week being rendered
 * highlighted_entry is the index of a highlighted entry
 * editable is a flag indicating whether to include controls to edit the
 *          schedule. */
/* exported renderSchedule */
function renderSchedule(sched, zones, dow, highlighted_entry, editable) {
    var mk_row = function(entry) {
        var tr = $("<tr>");
        var td_start = $("<td>").text(entry.when);
        var td_remove = $("<td>").addClass("remove");
        var remove_btn = $("<button>");
        remove_btn.addClass("flat").text("Remove");
        remove_btn.data("time", entry.when);
        remove_btn.data("day", dow);
        remove_btn.data("tablerow", tr);
        remove_btn.click(remove_click);
        td_remove.append(remove_btn);

        tr.append(td_start);
        zones.forEach(function(zone) {
            var zone_temp = entry.zones.find(e => e.zone == zone.zone_id);
            if (zone_temp)
                tr.append($("<td>").text(zone_temp.temp.toString())
                                   .append("&deg;C"));
            else
                tr.append($("<td>").text('--'));
        });
        if (editable)
            tr.append(td_remove);

        return tr;
    };
    var add_click = function() {
        var timeval = $("#time_" + dow)[0].value;
        /* This kinda sucks: find right place in table to put the value: */
        var pos = 1;
        for (var i = 0; i < sched.length; i++) {
            /* All time in %H:%M format, 24h clock, so this works.
             * But it's super ugly. */
            if (sched[i].when < timeval) {
                pos += 1;
            }
        }
        
        var new_entry = {
            when: timeval,
            zones: zones.map(function(zone) {
                    var tempval = parseFloat($("#temp_" + dow.toString() + "_" + zone.zone_id)[0].value);
                    if (isNaN(tempval))
                        tempval = null;
                    return {
                        zone: zone.zone_id, 
                        temp: tempval
                        };
                   }).filter(e => e.temp) 
                   /* only include zones with values */
            };
        sched.splice(pos - 1, 0, new_entry);

        /* This is a bit nasty because it requires multiple API calls, so
         * some may succeed and others fail.  For now we just assume all or
         * none works for the purpose of updating the UI: */
        var tr = mk_row(new_entry);
        var success = false;
        var requests = []
        zones.forEach(function(zone) {
            var tempval = $("#temp_" + dow.toString() + "_" + zone.zone_id)[0].value;
            if (tempval) {
                requests.push($.post({url: "api/schedule/new_entry",
                        data: {time: timeval, temp: tempval, day: dow, zone: zone.zone_id},
                        async: true,
                        success: function() {
                                $("#time_" + dow).val("");
                                $("#temp_" + dow.toString() + "_" + zone.zone_id).val("");
                                $("#time_" + dow).focus();
                                success = true;
                            }
                       }));
            }
        });
        $.when(requests).done(function(results) {
                $(table_sched).find("tr").eq(pos - 1).after(tr);
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
                    sched.splice(sched.findIndex(
                        x => (x.when == data.when)), 1);
                }
            });
    };

    var div_sched = [];
    div_sched.push($("<h1>").text(weekday[dow]));
    var table_sched = $("<table>");
    var head = $("<tr>").append($("<td>").text("Start"));
    zones.every(zone => head.append($("<td>").text(zone.name)));
    head.addClass("head");
    if (editable)
        head.append($("<td>"));
    table_sched.append(head);
    for (var i = 0; i < sched.length; i++) {
        var tr = mk_row(sched[i]);
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

        /* Time entry */
        var td_add_time = $("<td>").append(timefield);
        tr_add.append(td_add_time);

        /* Add button - added to row at end: */
        var add_btn = $('<button class="flat">Add</button>');
        add_btn.data("timefield", timefield);

        /* Temp entry for each zone */
        zones.forEach(function(zone) {
            var tempfield = $('<input type="number" placeholder="Celsius">');
            tempfield.attr("id", "temp_" + dow.toString() + "_" + zone.zone_id);
            tempfield.keypress(keyfn);
            add_btn.data("tempfield_" + zone.zone_id, tempfield);
            tr_add.append($("<td>").append(tempfield));
        });

        add_btn.attr("id", "add_" + dow);
        add_btn.click(add_click);
        tr_add.append($("<td>").append(add_btn));
        table_sched.append(tr_add);
    }

    div_sched.push(table_sched);

    return div_sched;
}

/* Updates the application with a full, editable, schedule.
 * schedule is an array object containing the schedule, i.e. each at
 *          index is an object with a time and temp field. */
/* exported renderFullSchedule */
function renderFullSchedule(schedule, zones) {
    /* Set up app title bar: */
    $("#title").html('<a href="#summary"><i class="material-icons">' +
                     'arrow_back</i></a> Edit Schedule');
    var schedule_div = $("<div>").attr('id', 'app');
    schedule = schedule.schedule;

    /* Render each day's schedule */
    for (var i = 0; i < 7; i++) {
        var day = renderSchedule(schedule[i], zones, i, -1, true);
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
    var current_div = $('<div id="current">');
    summary.zones.sort((a,b) => (a.zone_id > b.zone_id) ? 1 : 
                                 ((b.zone_id > a.zone_id) ? -1 : 0)); 

    summary.zones.forEach(function(zone) {
        var current_location_p = $("<h1>").text(zone.name);
        var current_p = $('<p>');
        var current_val = zone.current_temp ? zone.current_temp.toFixed(1) : "---";
        current_p.append(current_location_p);
        current_p.append($('<span class="current">').text(current_val).append("&deg;C "));

        current_p.append($('<span class="' + 
            (zone.target_override ? 'overridden' : 'target') +
            '">').text(zone.target == null ? "(---)" : "(" + zone.target.toString() + "").append("&deg;C)"));
        current_div.append(current_p);
        if (zone.target_override) {
            var override_text = $("<p>").text("Override until ");
            var until = new Date(zone.target_override.until);
            override_text.append(until.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}));
            current_div.append(override_text);
        }
    });

    /* Override */
    var override_p = $('<p align="right">');
    if (summary.zones.some(zone => zone.target_override)) {
        override_p.append(
            $('<button class="highlight">').html('Cancel override')
                                           .click(clear_override));
    }
    var override_click = function() {
        $("#override").show();
    };
    override_p.append(
            $('<button class="highlight">').html('Override')
                                          .click(override_click));
    current_div.append(override_p);
    schedule_div.append(current_div);

    var page = $("<div>").addClass("page");
    page.append(renderSchedule(summary.today,
                               summary.zones,
                               summary.server_day_of_week,
                               summary.target_entry));
    page.append('<div class="buttons">' +
                '<button onclick="window.location.hash = ' +
                ' \'#edit_schedule\'" class="flat">Edit Schedule</button>' +
                '</div>');
    page.append(mk_override(load_summary, summary.zones));

    schedule_div.append(page);

    $("#app").replaceWith(schedule_div);
}

