import React from "react";

import "./Sidebar.css";

import { useAuth } from "../context/AuthContext";


function Sidebar({ page, setPage }) {

const { logout: authLogout } = useAuth();

const logout = async () => {

try{

await authLogout();

alert("Logged Out Successfully");

}

catch(err){

console.log(err);

alert(err.message);

}

};



return (

<div className="sidebar">

<h2 className="logo">

🌿 AQI

<br/>

Insight Pro

</h2>
<ul>


<li

className={

page==="dashboard"

?

"active"

:

""

}

onClick={()=>

setPage(

"dashboard"

)

}

>

🏠 Dashboard

</li>





<li

className={

page==="alerts"

?

"active"

:

""

}

onClick={()=>

setPage(

"alerts"

)

}

>

⚠ Alerts

</li>
<li

className={

page==="heatmap"

?

"active"

:

""

}

onClick={()=>

setPage("heatmap")

}

>

🌍 Heatmap

</li>
<li

className={

page==="route"

?

"active"

:

""

}

onClick={()=>

setPage(

"route"

)

}

>

🗺 Route Planner

</li>






<li

className={

page==="notifications"

?

"active"

:

""

}

onClick={()=>

setPage(

"notifications"

)

}

>

🔔 Notifications

</li>







<li

className={

page==="profile"

?

"active"

:

""

}

onClick={()=>

setPage(

"profile"

)

}

>

👤 Profile

</li>







<li

className={

page==="settings"

?

"active"

:

""

}

onClick={()=>

setPage(

"settings"

)

}

>

⚙ Settings

</li>






<li

className="logout"

onClick={logout}

>

🚪 Logout

</li>


</ul>

</div>

);

}


export default Sidebar;