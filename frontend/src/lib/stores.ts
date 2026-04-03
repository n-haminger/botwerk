import type { User } from "./api.js";

let _user = $state<User | null>(null);
let _loading = $state(true);

export const auth = {
	get user() {
		return _user;
	},
	set user(value: User | null) {
		_user = value;
	},
	get isAuthenticated() {
		return _user !== null;
	},
	get loading() {
		return _loading;
	},
	set loading(value: boolean) {
		_loading = value;
	},
};
