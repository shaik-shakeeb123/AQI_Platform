import React, { useState } from "react";

function SearchBar({ onSearch }) {

const [city,setCity]=useState("");

const handleSearch=()=>{

if(city.trim()===""){

alert("Please enter a city");

return;

}

onSearch(city);

};


return(

<div className="search-box">


<div className="search-input-wrapper">

<span className="search-icon">

🔍

</span>


<input

type="text"

placeholder="Search city like Delhi, Mumbai..."

value={city}

onChange={(e)=>

setCity(

e.target.value

)

}

onKeyDown={(e)=>{

if(e.key==="Enter"){

handleSearch();

}

}}

/>

</div>




<button

className="search-btn"

onClick={handleSearch}

>

Check AQI

</button>


</div>

);

}

export default SearchBar;