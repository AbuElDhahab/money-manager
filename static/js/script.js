const editBtns = document.querySelectorAll(".edit-btn");
const cancelBtns = document.querySelectorAll(".cancel-btn");
const conformBtns = document.querySelectorAll(".conform-btn");

editBtns.forEach(editBtn => {
    editBtn.addEventListener("click", function (e) {
        const row = e.target.closest("tr");

        row.querySelectorAll("input:not([type='hidden']), select").forEach(input => {
            input.disabled = false;
        });

        row.querySelector(".cancel-btn").hidden = false;
        row.querySelector(".conform-btn").hidden = false;
        row.querySelector(".edit-btn").hidden = true;
    });
});

cancelBtns.forEach(cancelBtn => {
    cancelBtn.addEventListener("click", function (e) {
        const row = e.target.closest("tr");

        row.querySelectorAll("input:not([type='hidden']), select").forEach(input => {
            input.disabled = true;
        });

        row.querySelector(".conform-btn").hidden = true;
        row.querySelector(".cancel-btn").hidden = true;
        row.querySelector(".edit-btn").hidden = false;
    });
});